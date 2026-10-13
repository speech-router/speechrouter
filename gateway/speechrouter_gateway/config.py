"""Gateway settings. Every self-host/cloud difference is an env var read here."""

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class KeyStoreKind(StrEnum):
    none = "none"  # dev only: auth disabled, logs a loud warning
    local = "local"  # keys from SPEECHROUTER_KEYS env
    cloud = "cloud"  # Redis cache backed by shared Postgres


class UsageEmitterKind(StrEnum):
    log = "log"  # structured log line per usage event
    redis = "redis"  # XADD to the usage stream consumed by cloud


class AudioSinkKind(StrEnum):
    none = "none"  # default everywhere, including api.speechrouter.ai
    s3 = "s3"  # stream raw session audio to an S3 bucket you own


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPEECHROUTER_", env_file=".env", extra="ignore")

    keystore: KeyStoreKind = KeyStoreKind.local
    usage_emitter: UsageEmitterKind = UsageEmitterKind.log

    # local keystore: comma-separated plaintext keys ("sk_local_abc,sk_local_def")
    keys: str = ""

    redis_url: str = "redis://localhost:6379/0"

    # Session guards
    max_concurrent_streams: int = 20  # per org (cloud) / key (local); 0 = unlimited
    max_session_seconds: int = 4 * 60 * 60
    idle_timeout_seconds: int = 60
    ring_buffer_seconds: int = 10

    # TTS + live voice (PLAN-tts-live.md). On for self-host; cloud deploys set
    # them false until cloud billing prices unit-based events. A disabled
    # kind vanishes from /v1/models and its endpoints answer model_not_found.
    enable_tts: bool = True
    enable_live: bool = True
    max_tts_input_chars: int = 4096  # per request / per /v1/speak segment
    # live sessions cost ~10-50x STT per minute: separate, tighter cap
    max_concurrent_live: int = 5  # per org (cloud) / key (local); 0 = unlimited
    max_live_session_seconds: int = 60 * 60  # OpenAI caps upstream at 60 min
    live_idle_timeout_seconds: int = 120
    live_checkpoint_seconds: int = 60  # usage checkpoint cadence (§2.6)
    # admission needs this much balance (micro-USD; cloud mode only, house
    # keys only). 5_000_000 = $5. 0 disables the floor.
    live_min_balance_microusd: int = 5_000_000
    # How to read Gemini Live usageMetadata until a live probe settles it
    # (docs/providers/gemini.md): per_message = sum every report,
    # cumulative = keep the running max.
    gemini_live_usage_semantics: str = "per_message"

    # Provider credentials (gateway-owned; BYOK arrives via the cloud keystore)
    deepgram_api_key: str = ""
    soniox_api_key: str = ""
    assemblyai_api_key: str = ""
    speechmatics_api_key: str = ""
    telnyx_api_key: str = ""
    mistral_api_key: str = ""
    palabra_api_key: str = ""
    # Gemini Live transcription — a plain Gemini API key from
    # aistudio.google.com. Unrelated to the google_* settings below:
    # that is Google Cloud Speech-to-Text, a different product with a
    # different credential.
    gemini_api_key: str = ""
    # Palabra endpoints are per-region; STT is served from `eu` only today.
    palabra_region: str = "eu"
    meta_api_key: str = ""  # Meta Model API key (LLM|...), Muse Voice Transcribe
    xai_api_key: str = ""  # xAI API key (console.x.ai), Grok Voice Transcribe
    google_project_id: str = ""
    # Full service-account JSON as a string secret -- keeps prod deploys on
    # the same plain-env-var pattern as every other provider (no file
    # mounting in Kamal). Local dev can still use GOOGLE_APPLICATION_CREDENTIALS
    # pointing at a file; this takes precedence when set.
    google_credentials_json: str = ""

    # observability — empty means disabled
    sentry_dsn: str = ""
    logtail_source_token: str = ""
    logtail_host: str = "in.logs.betterstack.com"  # auth via ADC (GOOGLE_APPLICATION_CREDENTIALS)
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    openai_api_key: str = ""
    # Upstream base URLs for TTS + live. Overridable for self-host egress
    # proxies and for the local smoke harness (mock upstream); the realtime
    # WebSocket URL is derived (https->wss). STT adapters keep their own.
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    elevenlabs_api_key: str = ""
    cartesia_api_key: str = ""
    groq_api_key: str = ""
    # TTS-only providers (docs/providers/tts/*.md)
    rime_api_key: str = ""
    hume_api_key: str = ""
    lmnt_api_key: str = ""
    inworld_api_key: str = ""  # Basic-auth credential string from the Inworld portal
    fishaudio_api_key: str = ""
    playht_api_key: str = ""
    playht_user_id: str = ""
    minimax_api_key: str = ""
    murf_api_key: str = ""
    resemble_api_key: str = ""
    smallest_api_key: str = ""
    together_api_key: str = ""  # Kokoro tier (non-PHI only per Together ToS)
    # Google Cloud TTS REST accepts an API key; independent of the STT
    # service-account settings below
    google_tts_api_key: str = ""
    # JSON {"<provider>": "<base url>"}: per-provider TTS upstream override
    # (egress proxies, the local smoke harness). Empty = vendor defaults.
    tts_base_urls: str = ""

    # Optional audio persistence -- off by default. When enabled, session
    # audio streams to this bucket via real multipart upload (never
    # buffered whole in memory). Credentials/region default to the AWS
    # Transcribe settings above when left blank -- set the _-prefixed
    # variants only if the sink should use a different account/bucket.
    audio_sink: AudioSinkKind = AudioSinkKind.none
    audio_sink_bucket: str = ""
    audio_sink_prefix: str = ""
    audio_sink_region: str = ""
    audio_sink_access_key: str = ""
    audio_sink_secret_key: str = ""


def tts_base_url(cfg: Settings, provider: str, default: str) -> str:
    """Upstream base for a TTS provider, honouring tts_base_urls."""
    if not cfg.tts_base_urls:
        return default
    import json  # noqa: PLC0415

    try:
        overrides = json.loads(cfg.tts_base_urls)
    except json.JSONDecodeError:
        return default
    value = overrides.get(provider) if isinstance(overrides, dict) else None
    return value.rstrip("/") if isinstance(value, str) and value else default


@lru_cache
def settings() -> Settings:
    return Settings()
