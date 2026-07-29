"""Short-lived tokens for client-side use.

API keys must never ship to a browser or mobile app. Instead, the customer's
backend calls POST /v1/tokens with its real key and hands the resulting
`st_...` token to the client. The token authenticates exactly like a key
(same query param / header), inherits the parent key's identity for billing,
and expires after a short TTL — long enough to CONNECT, not a session cap:
once the socket is open, the stream runs regardless of expiry.

Cloud mode stores tokens in Redis (multi-instance safe); local/self-host
mode keeps them in process memory (single instance is the normal topology).
"""

import hashlib
import json
import secrets
import time
from abc import ABC, abstractmethod

from ..logging import logger
from .keystore import KeyRecord

TOKEN_PREFIX = "st_"
REDIS_PREFIX = "speechrouter:token:"

MIN_TTL = 10
MAX_TTL = 300
DEFAULT_TTL = 60


def is_token(presented: str) -> bool:
    return presented.startswith(TOKEN_PREFIX)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenStore(ABC):
    @abstractmethod
    async def mint(self, record: KeyRecord, ttl_seconds: int) -> tuple[str, float]:
        """Create a token for the given key identity. Returns (token, expires_at)."""

    @abstractmethod
    async def lookup(self, token: str) -> KeyRecord | None:
        """Return the identity behind a live token, None if unknown/expired."""


class LocalTokenStore(TokenStore):
    def __init__(self) -> None:
        self._tokens: dict[str, tuple[float, KeyRecord]] = {}

    async def mint(self, record: KeyRecord, ttl_seconds: int) -> tuple[str, float]:
        token = f"{TOKEN_PREFIX}{secrets.token_hex(24)}"
        expires_at = time.time() + ttl_seconds
        self._tokens[_hash(token)] = (expires_at, record)
        # opportunistic sweep so long-lived processes don't accumulate
        if len(self._tokens) > 10_000:
            now = time.time()
            self._tokens = {h: v for h, v in self._tokens.items() if v[0] > now}
        return token, expires_at

    async def lookup(self, token: str) -> KeyRecord | None:
        entry = self._tokens.get(_hash(token))
        if entry is None or entry[0] < time.time():
            return None
        return entry[1]


class RedisTokenStore(TokenStore):
    def __init__(self, redis) -> None:  # noqa: ANN001 - aioredis client
        self._redis = redis

    async def mint(self, record: KeyRecord, ttl_seconds: int) -> tuple[str, float]:
        token = f"{TOKEN_PREFIX}{secrets.token_hex(24)}"
        payload = json.dumps({"key_id": record.key_id, "org_id": record.org_id})
        await self._redis.set(f"{REDIS_PREFIX}{_hash(token)}", payload, ex=ttl_seconds)
        return token, time.time() + ttl_seconds

    async def lookup(self, token: str) -> KeyRecord | None:
        try:
            raw = await self._redis.get(f"{REDIS_PREFIX}{_hash(token)}")
        except Exception:
            logger.error("token lookup redis failure", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return KeyRecord(
            key_id=str(payload.get("key_id", "")),
            org_id=str(payload.get("org_id", "")) or None,
        )


async def resolve_credentials(state, presented: str) -> KeyRecord | None:  # noqa: ANN001
    """One auth entrypoint for every endpoint: tokens and keys both work."""
    if is_token(presented):
        return await state.token_store.lookup(presented)
    return await state.keystore.lookup(presented)
