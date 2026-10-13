"""POST /v1/audio/speech — OpenAI-compatible text-to-speech (PLAN §1.1 A).

The body is OpenAI's shape with our slug in `model`, so the OpenAI SDK works
unchanged against base_url=<gateway>/v1. Audio streams back with chunked
transfer as the provider produces it.

Errors before the first audio byte use the standard JSON envelope and status
map. After the first byte the status line is already sent: a provider
failure cuts the stream short (logged, metered as provider_error) — the same
tradeoff OpenAI makes.

Usage is emitted exactly once per request from the generator's finally, so
client aborts are metered too (generated audio was paid for upstream).
"""

import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..alerting import customer_facing, report_provider_failure
from ..auth.byok import apply_byok, org_blocked
from ..auth.tokens import resolve_credentials
from ..logging import logger
from ..metering import UsageEvent
from ..protocol.events import Code
from ..providers.base import ProviderStreamError
from ..router.resolver import ResolvedTTS, ResolveError, TTSRequest, resolve_tts
from ..tts.runner import TTSRun, list_cost, tts_units
from .transcriptions import _error

router = APIRouter()


class SpeechBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    input: str = Field(min_length=1)
    voice: str | None = None
    response_format: str | None = None  # default: mp3, or wav for pcm-only models
    sample_rate: int | None = None
    speed: float | None = None
    instructions: str | None = None
    language: str | None = None
    stream: bool = True
    provider_params: dict = Field(default_factory=dict)


def _status_code(exc: ProviderStreamError) -> Code:
    if exc.code == "timeout":
        return Code.provider_timeout
    if exc.code == "invalid_request":
        return Code.invalid_request
    return Code.provider_error


@router.post("/v1/audio/speech")
async def speech(request: Request, body: SpeechBody):
    state = request.app.state
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    record = await resolve_credentials(state, key)
    if record is None:
        return _error(Code.auth_failed, "invalid or missing API key")
    redis = getattr(state.keystore, "redis", None)
    if await org_blocked(redis, record.org_id):
        return _error(
            Code.insufficient_credits,
            "credit balance is empty — top up at speechrouter.ai/settings/billing",
        )

    settings, byok = await apply_byok(
        state.settings, redis, record.org_id, {body.model.split("/", 1)[0]}
    )
    try:
        resolved = resolve_tts(
            body.model,
            TTSRequest(
                text_length=len(body.input),
                voice=body.voice,
                format=body.response_format,
                sample_rate=body.sample_rate,
                speed=body.speed,
                instructions=body.instructions,
                language=body.language,
                provider_params=body.provider_params,
            ),
            settings,
            state.catalog,
        )
    except ResolveError as exc:
        return _error(exc.code, exc.message)

    request_id = f"tts_{uuid.uuid4().hex[:16]}"
    job = _SpeechJob(state, resolved, body.input, request_id, record.key_id, byok)
    try:
        first = await job.first_chunk()
    except ProviderStreamError as exc:
        await job.finish("provider_error")
        report_provider_failure(exc.provider, resolved.slug, str(exc), code=exc.code)
        safe = byok or exc.code == "invalid_request"
        return _error(_status_code(exc), str(exc) if safe else customer_facing(exc.code))
    except Exception:
        await job.finish("error")
        logger.error("tts crashed", exc_info=True, extra={"model": resolved.slug})
        return _error(Code.internal_error, "internal error")

    headers = {
        "X-SpeechRouter-Request-Id": request_id,
        "X-SpeechRouter-Model": resolved.slug,
        "X-SpeechRouter-Characters": str(len(body.input)),
    }
    if not body.stream:
        chunks = [first]
        async for chunk in job.rest():
            chunks.append(chunk)
        if job.status != "completed":
            return _error(Code.provider_error, customer_facing(None))
        headers["X-SpeechRouter-Cost-Usd"] = f"{job.cost:.6f}"
        return Response(b"".join(chunks), media_type=resolved.content_type, headers=headers)
    return StreamingResponse(
        job.rest(prefix=first), media_type=resolved.content_type, headers=headers
    )


class _SpeechJob:
    """Owns the adapter, the run, and the single usage emission."""

    def __init__(self, state, resolved: ResolvedTTS, text: str, request_id: str,
                 key_id: str, byok: bool):
        self._state = state
        self._resolved = resolved
        self._text = text
        self._id = request_id
        self._key_id = key_id
        self._byok = byok
        self._adapter = resolved.build()
        self._run = TTSRun(resolved)
        self._iter = self._run.stream(self._adapter, text).__aiter__()
        self._started = time.monotonic()
        self._emitted = False
        self.cost = 0.0
        self.status = ""

    async def first_chunk(self) -> bytes:
        try:
            return await self._iter.__anext__()
        except StopAsyncIteration:
            return b""

    async def rest(self, prefix: bytes | None = None) -> AsyncIterator[bytes]:
        status = "client_disconnect"
        try:
            if prefix:
                yield prefix
            async for chunk in self._iter:
                yield chunk
            status = "completed"
        except ProviderStreamError as exc:
            status = "provider_error"
            report_provider_failure(exc.provider, self._resolved.slug, str(exc), code=exc.code)
        except Exception:
            status = "error"
            logger.error("tts stream crashed", exc_info=True,
                         extra={"model": self._resolved.slug})
        finally:
            await self.finish(status)

    async def finish(self, status: str) -> None:
        if self._emitted:
            return
        self._emitted = True
        self.status = status
        await self._adapter.close()
        usage = self._run.usage
        units = tts_units(self._resolved.entry, usage, produced=self._run.produced_bytes > 0)
        self.cost = list_cost(self._resolved.entry, units, self._byok)
        seconds = round(self._run.audio_seconds, 3)
        event = UsageEvent(
            session_id=self._id,
            key_id=self._key_id,
            model=self._resolved.slug,
            kind="tts_batch",
            audio_seconds=seconds,
            billed_seconds=0.0,
            billing_basis="units",
            characters=usage.characters,
            status=status,
            byok=self._byok,
            units=units,
            units_estimated=usage.estimated,
            session_seconds=round(time.monotonic() - self._started, 3),
            output_audio_seconds=seconds,
            list_cost_usd=self.cost,
        )
        logger.info("tts request finished", extra={
            "request_id": self._id, "model": self._resolved.slug, "status": status,
            "characters": usage.characters, "audio_seconds": seconds, "units": units,
        })
        try:
            await self._state.emitter.emit(event)
        except Exception:  # noqa: BLE001 - metering must never break the response
            logger.error("tts usage emit failed", exc_info=True)
