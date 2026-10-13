"""Live voice passthrough endpoints (PLAN §2.2).

- WSS /v1/realtime?model=<slug|model>   OpenAI Realtime (OpenAI SDKs with
  base_url=<gateway>/v1)
- WSS /ws/google.ai.generativelanguage.{v1beta,v1alpha}.GenerativeService
  .BidiGenerateContent[Constrained]      Gemini Live (google-genai with
  http_options.base_url=<gateway>), alias WSS /v1/live/gemini

Admission mirrors /v1/listen (key or st_ token, blocked orgs, BYOK) plus a
minimum balance and a separate concurrency cap: a live minute costs far
more than an STT minute.
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket

from ..auth.byok import apply_byok, org_blocked
from ..auth.tokens import resolve_credentials
from ..live.dialects import GEMINI, OPENAI, Dialect
from ..live.proxy import LiveSession, ResolvedLive
from ..protocol.events import Code
from ..router.resolver import ResolveError, resolve_live

router = APIRouter()

FIRST_FRAME_TIMEOUT = 10.0
_GEMINI_PATHS = [
    f"/ws/google.ai.generativelanguage.{version}.GenerativeService.{method}"
    for version in ("v1beta", "v1alpha")
    for method in ("BidiGenerateContent", "BidiGenerateContentConstrained")
]


async def _reject(websocket: WebSocket, dialect: Dialect, code: Code, message: str) -> None:
    frame = dialect.error_frame(code.value, message)
    with contextlib.suppress(Exception):
        if frame is not None:
            await websocket.send_text(frame)
        await websocket.close(code=1008, reason=f"{code.value}: {message}"[:123])


async def _first_frame(websocket: WebSocket) -> str | bytes | None:
    try:
        async with asyncio.timeout(FIRST_FRAME_TIMEOUT):
            message = await websocket.receive()
    except TimeoutError:
        return None
    if message["type"] == "websocket.disconnect":
        return None
    data = message.get("bytes")
    return data if data is not None else message.get("text")


LIVE_MIN_BALANCE_KEY = "speechrouter:live_min_balance"


async def _live_floor(redis, default: int) -> int:
    """Cloud publishes the floor (micro-USD) at speechrouter:live_min_balance;
    the setting is the fallback when the key is absent or unreadable."""
    if redis is None:
        return default
    try:
        raw = await redis.get(LIVE_MIN_BALANCE_KEY)
        return int(raw) if raw is not None else default
    except Exception:  # noqa: BLE001 - fail to the configured floor
        return default


async def _balance_ok(redis, org_id: str | None, floor: int) -> bool:
    if redis is None or not org_id or floor <= 0:
        return True
    try:
        raw = await redis.get(f"speechrouter:balance:{org_id}")
    except Exception:  # noqa: BLE001 - fail open, like org_blocked
        return True
    return raw is None or int(raw) >= floor


async def serve_live(websocket: WebSocket, dialect: Dialect) -> None:
    await websocket.accept(subprotocol=dialect.accept_subprotocol(websocket))
    state = websocket.app.state
    redis = getattr(state.keystore, "redis", None)

    record = await resolve_credentials(state, dialect.credentials(websocket))
    if record is None:
        await _reject(websocket, dialect, Code.auth_failed, "invalid or missing API key")
        return
    if await org_blocked(redis, record.org_id):
        await _reject(websocket, dialect, Code.insufficient_credits,
                      "credit balance is empty — top up at speechrouter.ai/settings/billing")
        return

    first_frame = None
    model = dialect.model_from_url(websocket)
    if model is None:
        first_frame = await _first_frame(websocket)
        model = dialect.model_from_first_frame(first_frame) if first_frame else None
        if not model:
            await _reject(websocket, dialect, Code.invalid_request,
                          "first message must be `setup` naming a model")
            return
    if not model:
        await _reject(websocket, dialect, Code.invalid_request, "model query param is required")
        return

    slug = dialect.slug(model)
    settings, byok = await apply_byok(state.settings, redis, record.org_id, {dialect.provider})
    try:
        entry, native_model = resolve_live(slug, dialect.name, settings, state.catalog)
    except ResolveError as exc:
        await _reject(websocket, dialect, exc.code, exc.message)
        return
    floor = await _live_floor(redis, state.settings.live_min_balance_microusd)
    if not byok and not await _balance_ok(redis, record.org_id, floor):
        await _reject(websocket, dialect, Code.insufficient_credits,
                      f"live sessions need a balance of at least ${floor / 1_000_000:.2f} — "
                      "top up at speechrouter.ai/settings/billing")
        return

    scope = record.org_id or record.key_id
    if not state.live_concurrency.acquire(scope):
        await _reject(websocket, dialect, Code.concurrency_exceeded,
                      f"concurrent live session limit ({state.settings.max_concurrent_live}) "
                      "reached for this organization")
        return
    session = LiveSession(
        websocket=websocket,
        dialect=dialect,
        resolved=ResolvedLive(slug=slug, model=native_model, entry=entry, settings=settings),
        emitter=state.emitter,
        catalog=state.catalog,
        key_id=record.key_id,
        settings=state.settings,
        byok=byok,
        org_id=record.org_id,
        redis=redis,
        first_frame=first_frame,
    )
    try:
        await session.run()
    finally:
        state.live_concurrency.release(scope)


@router.websocket("/v1/realtime")
async def openai_realtime(websocket: WebSocket) -> None:
    await serve_live(websocket, OPENAI)


async def gemini_live(websocket: WebSocket) -> None:
    await serve_live(websocket, GEMINI)


for _path in [*_GEMINI_PATHS, "/v1/live/gemini"]:
    router.add_api_websocket_route(_path, gemini_live)
