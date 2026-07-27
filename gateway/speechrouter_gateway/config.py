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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPEECHROUTER_", env_file=".env", extra="ignore")

    keystore: KeyStoreKind = KeyStoreKind.local
    usage_emitter: UsageEmitterKind = UsageEmitterKind.log

    # local keystore: comma-separated plaintext keys ("sk_local_abc,sk_local_def")
    keys: str = ""

    redis_url: str = "redis://localhost:6379/0"

    # Session guards
    max_session_seconds: int = 4 * 60 * 60
    idle_timeout_seconds: int = 60
    ring_buffer_seconds: int = 10

    # Provider credentials (gateway-owned; BYOK arrives via the cloud keystore)
    deepgram_api_key: str = ""
    soniox_api_key: str = ""
    assemblyai_api_key: str = ""
    speechmatics_api_key: str = ""
    mistral_api_key: str = ""
    google_project_id: str = ""  # auth via ADC (GOOGLE_APPLICATION_CREDENTIALS)
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    openai_api_key: str = ""
    elevenlabs_api_key: str = ""
    cartesia_api_key: str = ""
    groq_api_key: str = ""


@lru_cache
def settings() -> Settings:
    return Settings()
