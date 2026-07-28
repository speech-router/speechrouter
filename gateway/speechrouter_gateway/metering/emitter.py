"""Usage events. Fire-and-forget from the hot path; must never add stream latency."""

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

from ..config import Settings, UsageEmitterKind
from ..logging import logger


@dataclass(frozen=True)
class UsageEvent:
    session_id: str
    key_id: str
    model: str  # resolved slug, e.g. deepgram/nova-3
    kind: str  # stt_stream | stt_batch | tts_stream | tts_batch
    audio_seconds: float = 0.0
    characters: int = 0
    provider_switches: int = 0
    status: str = "completed"  # completed | client_disconnect | provider_error | error
    byok: bool = False  # org-supplied provider key; billed at the routing fee only
    ts: float = field(default_factory=time.time)


class UsageEmitter(ABC):
    @abstractmethod
    async def emit(self, event: UsageEvent) -> None:
        """Record one usage event. Implementations swallow their own failures:
        a metering outage must never take down a live stream."""


class LogUsageEmitter(UsageEmitter):
    """Self-host: one structured log line per event."""

    async def emit(self, event: UsageEvent) -> None:
        logger.info("usage", extra={"usage": asdict(event)})


def build_emitter(cfg: Settings) -> UsageEmitter:
    match cfg.usage_emitter:
        case UsageEmitterKind.log:
            return LogUsageEmitter()
        case UsageEmitterKind.redis:
            from .redis_emitter import RedisUsageEmitter  # noqa: PLC0415 - optional path

            return RedisUsageEmitter(cfg.redis_url)
