"""POST /v1/tokens — mint short-lived client tokens from a real API key."""

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth.tokens import DEFAULT_TTL, MAX_TTL, MIN_TTL, is_token

router = APIRouter()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "type": "invalid_request_error"}},
    )


@router.post("/v1/tokens")
async def mint_token(request: Request) -> JSONResponse:
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
    return JSONResponse(
        {
            "token": token,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at)),
            "ttl_seconds": ttl,
        }
    )
