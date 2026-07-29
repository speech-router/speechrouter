"""POST /v1/audio/transcriptions — OpenAI-compatible batch STT.

Accepts multipart `file` or a `url` form field (the gateway downloads it, so
every provider gets URL support regardless of upstream). Errors use the
OpenAI envelope: {"error": {"code", "message", "type"}}.
"""

import json
import time
import uuid

import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from ..auth.byok import apply_byok, org_blocked
from ..logging import logger
from ..metering import UsageEvent
from ..protocol.events import Code
from ..providers.base import ProviderStreamError
from ..router.resolver import ResolveError, StreamRequest, resolve_batch
from . import formatters

router = APIRouter()

MAX_UPLOAD_BYTES = 250 * 1024 * 1024
MAX_URL_BYTES = 250 * 1024 * 1024

_STATUS = {
    Code.auth_failed: 401,
    Code.key_revoked: 401,
    Code.insufficient_credits: 402,
    Code.rate_limited: 429,
    Code.concurrency_exceeded: 429,
    Code.invalid_request: 400,
    Code.model_not_found: 404,
    Code.unsupported_capability: 400,
    Code.unsupported_encoding: 400,
    Code.payload_too_large: 413,
    Code.provider_error: 502,
    Code.provider_timeout: 504,
    Code.all_providers_failed: 502,
    Code.internal_error: 500,
}


def _error(code: Code, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=_STATUS.get(code, 500),
        content={"error": {"code": code.value, "message": message, "type": "invalid_request_error"
                           if _STATUS.get(code, 500) < 500 else "api_error"}},
    )


@router.post("/v1/audio/transcriptions")
async def transcribe(
    request: Request,
    model: str = Form(...),
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    language: str | None = Form(None),
    response_format: str = Form("json"),
    diarization: bool = Form(False),
    include_raw: bool = Form(False),
    keyterms: str | None = Form(None),
    provider_params: str | None = Form(None),
):
    state = request.app.state
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    record = await state.keystore.lookup(key)
    if record is None:
        return _error(Code.auth_failed, "invalid or missing API key")

    if response_format not in {"json", "verbose_json", "srt", "vtt", "text"}:
        return _error(Code.invalid_request, f"unknown response_format '{response_format}'")
    if (file is None) == (url is None):
        return _error(Code.invalid_request, "provide exactly one of `file` or `url`")

    extra: dict = {}
    if provider_params:
        try:
            parsed = json.loads(provider_params)
            if isinstance(parsed, dict):
                extra = parsed
        except json.JSONDecodeError:
            return _error(Code.invalid_request, "provider_params must be a JSON object")

    stream_request = StreamRequest(
        language=language,
        diarization=diarization,
        include_raw=include_raw,
        keyterms=tuple(t.strip() for t in (keyterms or "").split(",") if t.strip()),
        provider_params=extra,
    )
    if await org_blocked(getattr(state.keystore, "redis", None), record.org_id):
        return _error(
            Code.insufficient_credits,
            "credit balance is empty — top up at speechrouter.ai/settings/billing",
        )

    settings, byok_used = await apply_byok(
        state.settings, getattr(state.keystore, "redis", None), record.org_id,
        {model.split("/", 1)[0]},
    )
    try:
        resolved = resolve_batch(model, stream_request, settings, state.catalog)
    except ResolveError as exc:
        return _error(exc.code, exc.message)

    if file is not None:
        audio = await file.read()
        content_type = file.content_type or "application/octet-stream"
    else:
        assert url is not None
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                audio = response.content
                content_type = response.headers.get("content-type", "application/octet-stream")
        except httpx.HTTPError as exc:
            return _error(Code.invalid_request, f"could not fetch url: {exc}")
        if len(audio) > MAX_URL_BYTES:
            return _error(Code.payload_too_large, "remote file exceeds 250MB limit")
    if len(audio) > MAX_UPLOAD_BYTES:
        return _error(Code.payload_too_large, "file exceeds 250MB limit")
    if not audio:
        return _error(Code.invalid_request, "empty audio payload")

    adapter = resolved.build()
    started = time.monotonic()
    status = "completed"
    transcript = None
    try:
        transcript = await adapter.transcribe(audio, content_type, resolved.config)
    except ProviderStreamError as exc:
        status = "provider_error"
        return _error(
            Code.provider_timeout if exc.code == "timeout" else Code.provider_error, str(exc)
        )
    except Exception:
        status = "error"
        logger.error("batch transcription crashed", exc_info=True, extra={"model": model})
        return _error(Code.internal_error, "internal error")
    finally:
        audio_seconds = 0.0
        if transcript is not None and transcript.end is not None:
            audio_seconds = transcript.end
        await state.emitter.emit(
            UsageEvent(
                session_id=f"batch_{uuid.uuid4().hex[:16]}",
                key_id=record.key_id,
                model=model,
                kind="stt_batch",
                audio_seconds=round(audio_seconds, 3),
                byok=byok_used,
                status=status,
            )
        )
        logger.info(
            "batch transcription",
            extra={"model": model, "status": status,
                   "elapsed_ms": round((time.monotonic() - started) * 1000)},
        )

    if response_format == "json":
        return JSONResponse(formatters.to_json(transcript))
    if response_format == "verbose_json":
        return JSONResponse(formatters.to_verbose_json(transcript, resolved.slug))
    if response_format == "srt":
        return PlainTextResponse(formatters.to_srt(transcript))
    if response_format == "vtt":
        return PlainTextResponse(formatters.to_vtt(transcript))
    return PlainTextResponse(transcript.text)
