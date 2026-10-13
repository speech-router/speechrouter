"""Provider plugin contract.

Everything outside providers/ knows only these classes. Every provider quirk —
Deepgram's speech_final vs is_final, Soniox's token algebra, AssemblyAI's turn
supersession, Speechmatics' ack-based backpressure — is absorbed inside an
adapter and comes out as normalized protocol events.

Interface facts derived from provider research (docs/providers/*.md):

- connect() returns only when the provider is READY TO ACCEPT AUDIO. For
  Speechmatics that means RecognitionStarted was received; for Soniox the
  config message was sent; for SDK providers the session started. Audio sent
  before readiness is a protocol error on at least one provider.
- Adapters emit timestamps RELATIVE TO THEIR OWN STREAM START. The session
  layer adds the session offset (it alone knows how much audio time preceded
  this adapter after a failover). Adapters never see the ring buffer.
- Adapters own their provider keepalive (Deepgram KeepAlive every 3-5s,
  Soniox keepalive <=20s, Speechmatics WS pings) via internal tasks. The
  gateway-level client keepalive is a separate concern.
- send_audio() may block: adapters with provider-side backpressure
  (Speechmatics AudioAdded acks) or pacing enforcement (AssemblyAI 3007,
  Soniox 408) throttle inside send_audio, which propagates backpressure up
  to the client socket naturally.
- finish() signals end of audio upstream (CloseStream / empty frame /
  EndOfStream{last_seq_no} / Terminate — per provider), then events()
  exhausts after the provider's flush completes.
- close() must be safe from ANY state, including mid-connect and post-error.
- Recoverable provider failures raise ProviderStreamError(recoverable=True)
  out of events(); the failover engine treats that as a switch trigger.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..protocol import (
    SpeechStarted,
    Transcript,
    UtteranceEnd,
)

# Events an STT adapter may yield. Times are adapter-relative seconds.
STTEvent = Transcript | SpeechStarted | UtteranceEnd


class ProviderStreamError(Exception):
    """A provider-side failure with a typed recoverability signal."""

    def __init__(self, message: str, *, recoverable: bool, provider: str, code: str = ""):
        super().__init__(message)
        self.recoverable = recoverable
        self.provider = provider
        self.code = code  # provider-native error type/code for logs


class BillingBasis:
    AUDIO_TIME = "audio_time"  # billed on audio duration processed
    SESSION_TIME = "session_time"  # billed on wall-clock connection time
    # session_time providers (Soniox, AssemblyAI): idle upstream connections
    # burn money — the session layer must close them aggressively.


@dataclass(frozen=True)
class Capabilities:
    streaming: bool = False
    batch: bool = False
    interim_results: bool = False
    word_timestamps: bool = False
    diarization: bool = False
    endpointing: bool = False
    keyterms: bool = False
    keyterms_max: int = 0
    languages: frozenset[str] = field(default_factory=frozenset)  # {"auto"} = autodetect
    encodings: frozenset[str] = field(default_factory=frozenset)  # our canonical names
    sample_rates: frozenset[int] = field(default_factory=frozenset)  # empty = flexible
    # Ingest constraints (from provider enforcement, not preference):
    realtime_pacing_required: bool = False  # provider rejects faster-than-realtime input
    chunk_ms_min: int = 0
    chunk_ms_max: int = 0  # 0 = unconstrained
    billing_basis: str = BillingBasis.AUDIO_TIME
    turn_based: bool = False  # Flux/ink-2 style server-driven turn lifecycle


@dataclass(frozen=True)
class STTConfig:
    """Normalized request config an adapter receives — already validated
    against Capabilities by the resolver."""

    model: str  # provider-native model name (slug suffix)
    encoding: str
    sample_rate: int
    channels: int = 1
    language: str | None = None
    interim_results: bool = True
    diarization: bool = False
    keyterms: tuple[str, ...] = ()
    include_raw: bool = False  # attach raw provider payloads to transcripts
    provider_params: dict = field(default_factory=dict)  # passthrough escape hatch


class STTStreamProvider(ABC):
    """One instance == one upstream streaming session. Never reused."""

    name: str  # provider id, e.g. "deepgram"
    capabilities: Capabilities

    @abstractmethod
    async def connect(self, config: STTConfig) -> None:
        """Open the upstream session. Returns only when ready to accept audio.
        Raises ProviderStreamError(recoverable=...) on failure."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Forward one audio chunk. May block for provider backpressure/pacing."""

    @abstractmethod
    def events(self) -> AsyncIterator[STTEvent]:
        """Yield normalized events, adapter-relative times. Exhausts after
        finish() completes upstream flush. Raises ProviderStreamError on
        provider failure."""

    @abstractmethod
    async def finish(self) -> None:
        """Signal end of audio. Idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down unconditionally. Safe from any state. Idempotent."""


class STTBatchProvider(ABC):
    name: str
    capabilities: Capabilities

    @abstractmethod
    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        """One-shot transcription. Returns a single final Transcript with words
        when the provider supports them."""


# ------------------------------------------------------------------ TTS
#
# TTS contract (PLAN-tts-live.md §1.2). One adapter instance per request.
# synthesize() yields encoded audio in config.format and fills the caller's
# TTSUsage as it goes — by exhaustion it must be complete; on cancellation
# (client barge-in, disconnect) it holds whatever the provider already
# reported, and the gateway meters that: generated audio was paid for.


@dataclass(frozen=True)
class TTSCapabilities:
    voices: frozenset[str] = field(default_factory=frozenset)  # empty = any string
    default_voice: str = ""
    # formats the adapter yields itself; the gateway adds wav/mulaw/alaw
    # wrappers around pcm for adapters whose native output is pcm only
    formats: frozenset[str] = field(default_factory=frozenset)
    sample_rates: frozenset[int] = field(default_factory=frozenset)  # pcm output rates
    max_input_chars: int = 0  # 0 = gateway default
    instructions: bool = False
    speed: bool = False


@dataclass(frozen=True)
class TTSConfig:
    model: str  # provider-native model name (slug suffix)
    voice: str
    format: str  # format requested FROM THE ADAPTER (after wrapper mapping)
    sample_rate: int = 24000
    speed: float | None = None
    instructions: str | None = None
    language: str | None = None
    provider_params: dict = field(default_factory=dict)


@dataclass
class TTSUsage:
    characters: int = 0
    audio_seconds: float = 0.0  # generated audio, when the adapter knows it
    tokens: dict[str, float] = field(default_factory=dict)  # UsageEvent.units keys
    estimated: bool = False


class TTSProvider(ABC):
    name: str
    capabilities: TTSCapabilities

    @abstractmethod
    def synthesize(self, text: str, config: TTSConfig, usage: TTSUsage) -> AsyncIterator[bytes]:
        """Yield audio chunks as the provider produces them. Raises
        ProviderStreamError before or during the stream."""

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release pooled resources. Safe from any state."""
