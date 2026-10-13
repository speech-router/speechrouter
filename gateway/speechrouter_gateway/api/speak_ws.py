"""WSS /v1/speak — streaming TTS (protocol: packages/spec, session: tts/session.py).

Query params: model (required), voice, encoding (linear16|mulaw|alaw|mp3|
opus — per model), sample_rate, speed, language, instructions,
provider_params (JSON). Auth exactly as /v1/listen: Authorization: Bearer,
`Sec-WebSocket-Protocol: bearer, <key>`, or ?api_key= (keys or st_ tokens).
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel

from ..auth.byok import apply_byok, org_blocked
from ..auth.tokens import resolve_credentials
from ..protocol import Error
from ..protocol.events import Code
from ..router.resolver import ResolveError, TTSRequest, resolve_tts
from ..tts.session import SpeakClosed, SpeakSession
from .listen_ws import _extract_key, _subprotocol_auth

router = APIRouter()

# wire encoding name -> TTS response_format. wav is REST-only: a WS stream
# has no single file to put a header on.
_ENCODINGS = {"linear16": "pcm", "pcm": "pcm", "mulaw": "mulaw", "alaw": "alaw",
              "mp3": "mp3", "opus": "opus"}


class SpeakTransport:
    def __init__(self, websocket: WebSocket):
        self._ws = websocket

    async def recv(self) -> bytes | str | None:
        try:
            message = await self._ws.receive()
        except RuntimeError:
            return None
        if message["type"] == "websocket.disconnect":
            return None
        data = message.get("bytes")
        if data is not None:
            return data
        return message.get("text") or ""

    async def send_event(self, event: BaseModel) -> None:
        try:
            await self._ws.send_text(event.model_dump_json(by_alias=True, exclude_none=True))
        except Exception as exc:
            raise SpeakClosed() from exc

    async def send_audio(self, data: bytes) -> None:
        try:
            await self._ws.send_bytes(data)
        except Exception as exc:
            raise SpeakClosed() from exc


def _parse(websocket: WebSocket) -> tuple[str, TTSRequest] | str:
    params = websocket.query_params
    encoding = params.get("encoding", "linear16")
    fmt = _ENCODINGS.get(encoding)
    if fmt is None:
        return f"unsupported encoding '{encoding}' on /v1/speak"
    provider_params: dict = {}
    if params.get("provider_params"):
        try:
            parsed = json.loads(params["provider_params"])
        except json.JSONDecodeError:
            return "provider_params must be a JSON object"
        if not isinstance(parsed, dict):
            return "provider_params must be a JSON object"
        provider_params = parsed
    try:
        sample_rate = int(params["sample_rate"]) if params.get("sample_rate") else None
        speed = float(params["speed"]) if params.get("speed") else None
    except ValueError:
        return "sample_rate and speed must be numbers"
    return params.get("model", ""), TTSRequest(
        voice=params.get("voice"), format=fmt, sample_rate=sample_rate, speed=speed,
        instructions=params.get("instructions"), language=params.get("language"),
        provider_params=provider_params,
    )


@router.websocket("/v1/speak")
async def speak(websocket: WebSocket) -> None:
    subprotocol_key = _subprotocol_auth(websocket)
    await websocket.accept(subprotocol="bearer" if subprotocol_key else None)
    state = websocket.app.state
    transport = SpeakTransport(websocket)

    async def reject(code: Code, message: str) -> None:
        with contextlib.suppress(SpeakClosed):
            await transport.send_event(
                Error(type="error", code=code, message=message, recoverable=False)
            )
        with contextlib.suppress(Exception):
            await websocket.close(code=1008)

    record = await resolve_credentials(state, subprotocol_key or _extract_key(websocket))
    if record is None:
        await reject(Code.auth_failed, "invalid or missing API key")
        return
    redis = getattr(state.keystore, "redis", None)
    if await org_blocked(redis, record.org_id):
        await reject(Code.insufficient_credits,
                     "credit balance is empty — top up at speechrouter.ai/settings/billing")
        return
    parsed = _parse(websocket)
    if isinstance(parsed, str):
        await reject(Code.invalid_request, parsed)
        return
    slug, request = parsed
    if not slug:
        await reject(Code.invalid_request, "model query param is required")
        return
    settings, byok = await apply_byok(state.settings, redis, record.org_id,
                                      {slug.split("/", 1)[0]})
    try:
        resolved = resolve_tts(slug, request, settings, state.catalog)
    except ResolveError as exc:
        await reject(exc.code, exc.message)
        return

    scope = record.org_id or record.key_id
    if not state.concurrency.acquire(scope):
        await reject(Code.concurrency_exceeded,
                     f"concurrent stream limit ({state.settings.max_concurrent_streams}) "
                     "reached for this organization")
        return
    session = SpeakSession(
        transport=transport, resolved=resolved, emitter=state.emitter, key_id=record.key_id,
        settings=state.settings, byok=byok, org_id=record.org_id, redis=redis,
    )
    try:
        await session.run()
    finally:
        state.concurrency.release(scope)
    # linger so `done` flushes through proxies before close (see listen_ws)
    try:
        async with asyncio.timeout(3):
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass
    except (TimeoutError, RuntimeError):
        pass
    with contextlib.suppress(Exception):
        await websocket.close()
