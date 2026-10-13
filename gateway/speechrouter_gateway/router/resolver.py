"""Slug resolution: "deepgram/nova-3" + requested features -> validated attempt.

Rejects impossible requests (unknown model, unsupported capability, missing
credentials) BEFORE any provider connection is opened."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from ..config import Settings
from ..protocol.events import Code
from ..providers.base import (
    BillingBasis,
    STTBatchProvider,
    STTConfig,
    STTStreamProvider,
    TTSConfig,
    TTSProvider,
)
from ..providers.registry import (
    ProviderNotConfigured,
    stt_batch_provider,
    stt_stream_provider,
    tts_provider,
)
from .catalog import Catalog


class ResolveError(Exception):
    def __init__(self, code: Code, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StreamRequest:
    encoding: str = "linear16"
    sample_rate: int = 16000
    channels: int = 1
    language: str | None = None
    interim_results: bool = True
    diarization: bool = False
    keyterms: tuple[str, ...] = ()
    include_raw: bool = False
    provider_params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedAttempt:
    slug: str
    config: STTConfig
    build: Callable[[], STTStreamProvider]
    billing_basis: str = BillingBasis.AUDIO_TIME
    # catalog list price (USD per billed second) — drives mid-session
    # credit metering; 0.0 = unpriced, never metered
    price_per_second_usd: float = 0.0


@dataclass(frozen=True)
class ResolvedBatch:
    slug: str
    config: STTConfig
    build: Callable[[], STTBatchProvider]


def resolve_batch(
    slug: str, request: StreamRequest, settings: Settings, catalog: Catalog
) -> ResolvedBatch:
    provider_id, _, model_name = slug.partition("/")
    if not provider_id or not model_name:
        raise ResolveError(Code.model_not_found, f"invalid model slug '{slug}'")
    registered = stt_batch_provider(provider_id)
    entry = catalog.find(slug)
    if (
        registered is None
        or entry is None
        or entry.get("kind", "stt") != "stt"
        or "batch" not in entry.get("modes", [])
    ):
        raise ResolveError(Code.model_not_found, f"'{slug}' is not available for batch")
    caps = registered.capabilities
    if request.diarization and not caps.diarization:
        raise ResolveError(Code.unsupported_capability, f"'{slug}' does not support diarization")
    try:
        _ = registered.build(settings)
    except ProviderNotConfigured as exc:
        raise ResolveError(Code.invalid_request, str(exc)) from exc
    config = STTConfig(
        model=model_name,
        encoding=request.encoding,
        sample_rate=request.sample_rate,
        channels=request.channels,
        language=request.language,
        interim_results=False,
        diarization=request.diarization,
        keyterms=request.keyterms,
        include_raw=request.include_raw,
        provider_params=request.provider_params,
    )
    return ResolvedBatch(slug=slug, config=config, build=partial(registered.build, settings))


def resolve_stream(
    slug: str, request: StreamRequest, settings: Settings, catalog: Catalog
) -> ResolvedAttempt:
    provider_id, _, model_name = slug.partition("/")
    if not provider_id or not model_name:
        raise ResolveError(Code.model_not_found, f"invalid model slug '{slug}'")

    registered = stt_stream_provider(provider_id)
    if registered is None:
        raise ResolveError(Code.model_not_found, f"unknown provider '{provider_id}'")
    entry = catalog.find(slug)
    if entry is None:
        raise ResolveError(Code.model_not_found, f"unknown model '{slug}'")
    if entry.get("kind", "stt") != "stt":
        raise ResolveError(
            Code.model_not_found, f"'{slug}' is a {entry.get('kind')} model, not speech-to-text"
        )

    caps = registered.capabilities
    if request.diarization and not caps.diarization:
        raise ResolveError(Code.unsupported_capability, f"'{slug}' does not support diarization")
    if caps.encodings and request.encoding not in caps.encodings:
        raise ResolveError(
            Code.unsupported_encoding, f"'{slug}' does not accept encoding '{request.encoding}'"
        )

    # Fail on missing credentials now, not mid-connect. Builders are cheap
    # constructors by contract; the probe instance is discarded.
    try:
        _ = registered.build(settings)
    except ProviderNotConfigured as exc:
        raise ResolveError(Code.invalid_request, str(exc)) from exc

    config = STTConfig(
        model=model_name,
        encoding=request.encoding,
        sample_rate=request.sample_rate,
        channels=request.channels,
        language=request.language,
        interim_results=request.interim_results,
        diarization=request.diarization,
        keyterms=request.keyterms,
        include_raw=request.include_raw,
        provider_params=request.provider_params,
    )
    return ResolvedAttempt(
        slug=slug,
        config=config,
        build=partial(registered.build, settings),
        billing_basis=registered.capabilities.billing_basis,
        price_per_second_usd=float(
            (entry.get("pricing") or {}).get("per_second_usd") or 0.0
        ),
    )


# ------------------------------------------------------------------ TTS

# gateway-side wrappers over a pcm-producing adapter (audio/pcm_codec.py)
PCM_WRAPPED_FORMATS = frozenset({"wav", "mulaw", "alaw"})
# telephony codecs default to 8 kHz; everything else keeps the native rate
_DEFAULT_RATE = {"mulaw": 8000, "alaw": 8000}

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
    "mulaw": "audio/PCMU",
    "alaw": "audio/PCMA",
}


@dataclass(frozen=True)
class TTSRequest:
    text_length: int = 0  # code points; 0 = unknown yet (/v1/speak validates per segment)
    voice: str | None = None
    format: str | None = None  # None: mp3 when the model has it (OpenAI's default), else wav
    sample_rate: int | None = None
    speed: float | None = None
    instructions: str | None = None
    language: str | None = None
    provider_params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedTTS:
    slug: str
    entry: dict  # catalog entry: pricing + per-model capabilities
    config: TTSConfig  # what the ADAPTER is asked for
    build: Callable[[], TTSProvider]
    out_format: str  # what the CLIENT receives
    out_sample_rate: int  # meaningful for pcm-family formats
    native_rate: int  # adapter pcm rate (for wrappers + duration math)
    wrap: bool  # gateway converts adapter pcm -> out_format/out_sample_rate
    max_input_chars: int

    @property
    def content_type(self) -> str:
        base = CONTENT_TYPES.get(self.out_format, "application/octet-stream")
        if self.out_format in {"pcm", "mulaw", "alaw"}:
            return f"{base};rate={self.out_sample_rate};channels=1"
        return base


def resolve_tts(
    slug: str, request: TTSRequest, settings: Settings, catalog: Catalog
) -> ResolvedTTS:
    provider_id, _, model_name = slug.partition("/")
    if not provider_id or not model_name:
        raise ResolveError(Code.model_not_found, f"invalid model slug '{slug}'")
    registered = tts_provider(provider_id)
    entry = catalog.find(slug)
    if registered is None or entry is None or entry.get("kind") != "tts":
        raise ResolveError(Code.model_not_found, f"'{slug}' is not an available TTS model")
    caps = entry.get("capabilities") or {}

    voices = caps.get("voices") or []
    voice = request.voice or caps.get("default_voice") or registered.capabilities.default_voice
    if not voice:
        raise ResolveError(Code.invalid_request, f"'{slug}' requires a voice")
    if voices and voice not in voices:
        raise ResolveError(
            Code.invalid_request,
            f"unknown voice '{voice}' for '{slug}' (one of: {', '.join(voices)})",
        )

    formats = caps.get("formats") or []
    fmt = request.format or ("mp3" if "mp3" in formats else "wav")
    if fmt not in formats:
        raise ResolveError(
            Code.unsupported_encoding,
            f"'{slug}' cannot produce '{fmt}' (one of: {', '.join(formats)})",
        )
    native_formats = registered.capabilities.formats
    wrap = fmt not in native_formats
    if wrap and not (fmt in PCM_WRAPPED_FORMATS and "pcm" in native_formats):
        raise ResolveError(Code.unsupported_encoding, f"'{slug}' cannot produce '{fmt}'")
    native_rate = max(registered.capabilities.sample_rates or {24000})
    rates = caps.get("output_sample_rates") or [native_rate]
    out_rate = request.sample_rate or _DEFAULT_RATE.get(fmt, native_rate)
    if fmt in {"pcm", "wav", "mulaw", "alaw"}:
        if out_rate not in rates:
            raise ResolveError(
                Code.unsupported_encoding,
                f"'{slug}' outputs sample_rate {', '.join(map(str, rates))}, not {out_rate}",
            )
        if out_rate != native_rate:
            wrap = True  # gateway decimates
    elif request.sample_rate is not None:
        raise ResolveError(Code.invalid_request, "sample_rate applies to pcm/wav/mulaw/alaw only")

    if request.instructions and not caps.get("instructions"):
        raise ResolveError(
            Code.unsupported_capability, f"'{slug}' does not accept instructions"
        )
    if request.speed is not None:
        if not caps.get("speed"):
            raise ResolveError(Code.unsupported_capability, f"'{slug}' does not accept speed")
        if not 0.25 <= request.speed <= 4.0:
            raise ResolveError(Code.invalid_request, "speed must be between 0.25 and 4.0")

    max_chars = min(
        caps.get("max_input_chars") or settings.max_tts_input_chars,
        settings.max_tts_input_chars,
    )
    if request.text_length > max_chars:
        raise ResolveError(
            Code.payload_too_large, f"input exceeds {max_chars} characters for '{slug}'"
        )

    try:
        _ = registered.build(settings)
    except ProviderNotConfigured as exc:
        raise ResolveError(Code.invalid_request, str(exc)) from exc

    config = TTSConfig(
        model=model_name,
        voice=voice,
        format="pcm" if wrap else fmt,
        sample_rate=native_rate,
        speed=request.speed,
        instructions=request.instructions,
        language=request.language,
        provider_params=request.provider_params,
    )
    return ResolvedTTS(
        slug=slug,
        entry=entry,
        config=config,
        build=partial(registered.build, settings),
        out_format=fmt,
        out_sample_rate=out_rate,
        native_rate=native_rate,
        wrap=wrap,
        max_input_chars=max_chars,
    )
