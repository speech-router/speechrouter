"""Cloud usage emitter: fire-and-forget XADD onto the usage stream.

The cloud app's Solid Queue consumer reads this stream with a consumer
group (at-least-once) and lands idempotent usage_events + ledger rows.
A metering outage must never touch a live stream, so every failure is
swallowed into a log line.
"""

import json
from dataclasses import asdict

import redis.asyncio as aioredis

from ..logging import logger
from .emitter import UsageEmitter, UsageEvent

USAGE_STREAM = "speechrouter:usage"


class RedisUsageEmitter(UsageEmitter):
    def __init__(self, redis_url: str, client: aioredis.Redis | None = None):
        self._redis = client or aioredis.from_url(redis_url, decode_responses=True)

    async def emit(self, event: UsageEvent) -> None:
        try:
            await self._redis.xadd(
                USAGE_STREAM,
                {"payload": json.dumps(asdict(event))},
                maxlen=100_000,
                approximate=True,
            )
        except Exception:
            logger.error(
                "usage emit failed (event logged here as fallback)",
                exc_info=True,
                extra={"usage": asdict(event)},
            )
