"""Wire types — mirrors packages/spec/events.schema.json (the protocol's
source of truth). Field names stay snake_case: what the socket carries is
what you type against."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ErrorCode = Literal[
    "auth_failed",
    "key_revoked",
    "insufficient_credits",
    "rate_limited",
    "concurrency_exceeded",
    "invalid_request",
    "model_not_found",
    "unsupported_capability",
    "unsupported_encoding",
    "payload_too_large",
    "provider_error",
    "provider_timeout",
    "all_providers_failed",
    "audio_timeout",
    "session_expired",
    "internal_error",
]


@dataclass(slots=True)
class Word:
    w: str
    start: float
    end: float
    conf: float | None = None
    speaker: int | None = None
    lang: str | None = None


@dataclass(slots=True)
class SessionOpen:
    type: Literal["session.open"]
    session_id: str
    model: str
    encoding: str | None = None
    sample_rate: int | None = None


@dataclass(slots=True)
class Transcript:
    type: Literal["transcript"]
    is_final: bool
    text: str
    words: list[Word] | None = None
    start: float | None = None
    end: float | None = None
    lang: str | None = None
    provider_raw: dict[str, Any] | None = None


@dataclass(slots=True)
class SpeechStarted:
    type: Literal["speech_started"]
    at: float


@dataclass(slots=True)
class UtteranceEnd:
    type: Literal["utterance_end"]
    at: float


@dataclass(slots=True)
class ProviderSwitched:
    type: Literal["provider_switched"]
    from_: str
    to: str
    resumed_at: float
    speaker_mapping_preserved: bool


@dataclass(slots=True)
class TextDelta:
    type: Literal["text.delta"]
    text: str


@dataclass(slots=True)
class Cleared:
    type: Literal["cleared"]
    last_seq: int


@dataclass(slots=True)
class KeepAlive:
    type: Literal["keepalive"]


@dataclass(slots=True)
class Done:
    type: Literal["done"]
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ErrorEvent:
    type: Literal["error"]
    code: str
    message: str
    provider: str | None = None
    recoverable: bool = False


ListenEvent = (
    SessionOpen
    | Transcript
    | SpeechStarted
    | UtteranceEnd
    | ProviderSwitched
    | TextDelta
    | Cleared
    | KeepAlive
    | Done
    | ErrorEvent
)

_EVENT_TYPES: dict[str, type] = {
    "session.open": SessionOpen,
    "transcript": Transcript,
    "speech_started": SpeechStarted,
    "utterance_end": UtteranceEnd,
    "provider_switched": ProviderSwitched,
    "text.delta": TextDelta,
    "cleared": Cleared,
    "keepalive": KeepAlive,
    "done": Done,
    "error": ErrorEvent,
}


def parse_event(payload: dict[str, Any]) -> ListenEvent | None:
    """Build the typed event for a wire payload; None for unknown types
    (forward compatibility: new server events never crash old clients)."""
    cls = _EVENT_TYPES.get(payload.get("type", ""))
    if cls is None:
        return None
    data = dict(payload)
    if cls is ProviderSwitched and "from" in data:
        data["from_"] = data.pop("from")
    if cls is Transcript and isinstance(data.get("words"), list):
        data["words"] = [
            Word(**{k: v for k, v in w.items() if k in Word.__dataclass_fields__})
            for w in data["words"]
        ]
    known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    try:
        return cls(**known)  # type: ignore[return-value]
    except TypeError:
        return None
