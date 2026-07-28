"""Cloud keystore: Redis-only lookups against keys the control plane syncs.

Contract with the cloud app (Rails is the writer of record):
- On mint:   SET   speechrouter:key:<sha256(plaintext)> -> {"key_id","org_id"}
- On revoke: DEL   speechrouter:key:<sha256>
Revocation is therefore instant — no per-gateway cache to invalidate, and a
Redis GET is ~sub-millisecond, well inside the hot-path budget. The gateway
never talks to Postgres or Rails.
"""

import hashlib
import json

import redis.asyncio as aioredis

from ..logging import logger
from .keystore import KeyRecord, KeyStore

KEY_PREFIX = "speechrouter:key:"


class CloudKeyStore(KeyStore):
    def __init__(self, redis_url: str, client: aioredis.Redis | None = None):
        self._redis = client or aioredis.from_url(redis_url, decode_responses=True)

    async def lookup(self, presented_key: str) -> KeyRecord | None:
        if not presented_key:
            return None
        digest = hashlib.sha256(presented_key.encode()).hexdigest()
        try:
            raw = await self._redis.get(f"{KEY_PREFIX}{digest}")
        except Exception:
            logger.error("cloud keystore redis lookup failed", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("cloud keystore: malformed key payload", extra={"digest": digest[:12]})
            return None
        return KeyRecord(
            key_id=str(payload.get("key_id", "")),
            org_id=str(payload.get("org_id", "")) or None,
        )
