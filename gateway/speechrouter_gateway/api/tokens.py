"""POST /v1/tokens — mint short-lived client tokens from a real API key."""

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth.tokens import DEFAULT_TTL, MAX_TTL, MIN_TTL, is_token
from ..logging import logger

router = APIRouter()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "type": "invalid_request_error"}},
    )


async def _mint(request: Request, ttl: int | None) -> JSONResponse | tuple[str, float, int]:
    state = request.app.state
    header = request.headers.get("authorization", "")
    presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not presented:
        return _error(401, "auth_failed", "Authorization: Bearer <api key> required")
    if is_token(presented):
        return _error(403, "auth_failed", "tokens cannot mint tokens — use your API key")

    record = await state.keystore.lookup(presented)
    if record is None:
        return _error(401, "auth_failed", "invalid or revoked API key")

    if ttl is None:
        ttl = DEFAULT_TTL
        try:
            body = await request.json()
            if isinstance(body, dict) and "ttl_seconds" in body:
                ttl = int(body["ttl_seconds"])
        except Exception:  # noqa: BLE001, S110 - empty/non-JSON body means defaults
            pass
    if not MIN_TTL <= ttl <= MAX_TTL:
        return _error(
            400, "invalid_request", f"ttl_seconds must be between {MIN_TTL} and {MAX_TTL}"
        )

    token, expires_at = await state.token_store.mint(record, ttl)
    logger.info(
        "client token minted",
        extra={"key_id": record.key_id, "org_id": record.org_id, "ttl_seconds": ttl},
    )
    return token, expires_at, ttl


@router.post("/v1/tokens")
async def mint_token(request: Request) -> JSONResponse:
    minted = await _mint(request, None)
    if isinstance(minted, JSONResponse):
        return minted
    token, expires_at, ttl = minted
    return JSONResponse(
        {
            "token": token,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at)),
            "ttl_seconds": ttl,
        }
    )


@router.post("/v1/realtime/client_secrets")
async def realtime_client_secret(request: Request) -> JSONResponse:
    """OpenAI-shaped alias so browser Realtime samples work unchanged: the
    returned `value` is an st_ token, used where OpenAI's ek_ secret goes.
    `expires_after.seconds` is clamped into our 10-300 s connect window.
    The `session` config is echoed, NOT pinned into the token (PLAN Q3)."""
    body: dict = {}
    try:
        parsed = await request.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:  # noqa: BLE001, S110 - empty body means defaults
        pass
    expires = body.get("expires_after") or {}
    try:
        seconds = int(expires.get("seconds", MAX_TTL))
    except (TypeError, ValueError):
        seconds = MAX_TTL
    minted = await _mint(request, max(MIN_TTL, min(MAX_TTL, seconds)))
    if isinstance(minted, JSONResponse):
        return minted
    token, expires_at, _ = minted
    return JSONResponse({"value": token, "expires_at": int(expires_at),
                         "session": body.get("session") or {}})
