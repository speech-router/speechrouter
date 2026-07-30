"""WSS /v1/listen — streaming STT."""

import asyncio
import json

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel

from ..auth.byok import apply_byok, org_blocked
from ..auth.tokens import resolve_credentials
from ..logging import logger
from ..protocol import Error
from ..protocol.events import Code
from ..router.resolver import ResolveError, StreamRequest, resolve_stream
from ..router.session import SessionClosed, STTSession
from .dg_compat import _CLOSE_CODES as DG_CLOSE_CODES
from .dg_compat import DGTransport, dg_ws_credentials, translate_params

router = APIRouter()


class StarletteTransport:
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
            raise SessionClosed() from exc


def _extract_key(websocket: WebSocket) -> str:
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return websocket.query_params.get("api_key", "")


def _parse_request(websocket: WebSocket) -> tuple[str, list[str], StreamRequest]:
    params = websocket.query_params
    slug = params.get("model", "")
    fallbacks = [s.strip() for s in params.get("fallbacks", "").split(",") if s.strip()]
    terms = tuple(t.strip() for t in params.get("keyterms", "").split(",") if t.strip())
    provider_params = {}
    raw_pp = params.get("provider_params")
    if raw_pp:
        try:
            parsed = json.loads(raw_pp)
            if isinstance(parsed, dict):
                provider_params = parsed
        except json.JSONDecodeError:
            pass
    request = StreamRequest(
        encoding=params.get("encoding", "linear16"),
        sample_rate=int(params.get("sample_rate", "16000")),
        channels=int(params.get("channels", "1")),
        language=params.get("language"),
        interim_results=params.get("interim_results", "true").lower() != "false",
        diarization=params.get("diarization", "false").lower() == "true",
        keyterms=terms,
        include_raw=params.get("include_raw", "false").lower() == "true",
        provider_params=provider_params,
    )
    return slug, fallbacks, request


async def _reject(transport: StarletteTransport, websocket: WebSocket, code: Code, message: str):
    try:
        await transport.send_event(
            Error(type="error", code=code, message=message, recoverable=False)
        )
    except SessionClosed:
        return
    await websocket.close(code=1008)


def _subprotocol_auth(websocket: WebSocket) -> str | None:
    """Credentials via `Sec-WebSocket-Protocol: bearer, <key>` — keeps keys
    out of URLs (query strings leak into access logs, proxies, and APM)."""
    header = websocket.headers.get("sec-websocket-protocol", "")
    parts = [p.strip() for p in header.split(",") if p.strip()]
    if len(parts) == 2 and parts[0] == "bearer":
        return parts[1]
    return None


@router.websocket("/v1/listen")
async def listen(websocket: WebSocket) -> None:
    # Dialect detection: Deepgram SDKs authenticate with the Token scheme
    # (header or ['token', key] subprotocol); everyone else speaks native.
    dg_key = dg_ws_credentials(websocket)
    subprotocol_key = None if dg_key else _subprotocol_auth(websocket)
    offered = websocket.headers.get("sec-websocket-protocol", "")
    subproto = None
    if dg_key and "token" in offered:
        subproto = "token"
    elif subprotocol_key:
        subproto = "bearer"
    # RFC 6455: if the client offered subprotocols, the accept must echo one.
    await websocket.accept(subprotocol=subproto)
    state = websocket.app.state

    if dg_key:
        slug, fallbacks, request = translate_params(websocket.query_params)
        transport = DGTransport(websocket, slug)

        async def reject(code: Code, message: str) -> None:
            try:
                await websocket.close(code=DG_CLOSE_CODES.get(code, 1011), reason=message[:120])
            except Exception:  # noqa: BLE001 - already closed is fine
                pass
    else:
        slug, fallbacks, request = _parse_request(websocket)
        transport = StarletteTransport(websocket)

        async def reject(code: Code, message: str) -> None:
            await _reject(transport, websocket, code, message)

    record = await resolve_credentials(state, dg_key or subprotocol_key or _extract_key(websocket))
    if record is None:
        await reject(Code.auth_failed, "invalid or missing API key")
        return

    if await org_blocked(getattr(state.keystore, "redis", None), record.org_id):
        await reject(
            Code.insufficient_credits,
            "credit balance is empty — top up at speechrouter.ai/settings/billing",
        )
        return

    if not slug:
        await reject(Code.invalid_request, "model query param is required")
        return
    providers = {s.split("/", 1)[0] for s in [slug, *fallbacks]}
    settings, byok_used = await apply_byok(
        state.settings, getattr(state.keystore, "redis", None), record.org_id, providers
    )
    try:
        attempts = [
            resolve_stream(s, request, settings, state.catalog)
            for s in [slug, *fallbacks]
        ]
    except ResolveError as exc:
        await reject(exc.code, exc.message)
        return

    scope = record.org_id or record.key_id
    if not state.concurrency.acquire(scope):
        await reject(
            Code.concurrency_exceeded,
            f"concurrent stream limit ({state.settings.max_concurrent_streams}) reached "
            "for this organization",
        )
        return

    session = STTSession(
        transport=transport,
        attempts=attempts,
        emitter=state.emitter,
        key_id=record.key_id,
        byok=byok_used,
        settings=state.settings,
    )
    try:
        await session.run()
    finally:
        state.concurrency.release(scope)
    # Linger: closing immediately after `done` can reset the TCP connection
    # before the final frames flush through proxies (observed as client-side
    # 1006 with `done` lost). Let the client read `done` and close first;
    # the timeout backstops clients that never close.
    try:
        async with asyncio.timeout(3):
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
    except (TimeoutError, RuntimeError):
        pass
    try:
        await websocket.close()
    except Exception:  # noqa: BLE001 - already closed is fine
        logger.debug("client socket already closed", extra={"session": session._session_id})
