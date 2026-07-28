"""API-key verification. The hot path calls lookup() once per connection."""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..config import KeyStoreKind, Settings
from ..logging import logger


@dataclass(frozen=True)
class KeyRecord:
    key_id: str  # stable identifier for logs/usage events (never the key itself)
    org_id: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class KeyStore(ABC):
    @abstractmethod
    async def lookup(self, presented_key: str) -> KeyRecord | None:
        """Return the record for a valid key, None for an invalid/revoked one."""


class NoAuthKeyStore(KeyStore):
    """Dev mode: everything is allowed. main.py logs a loud warning at boot."""

    async def lookup(self, presented_key: str) -> KeyRecord | None:
        return KeyRecord(key_id="dev")


class LocalKeyStore(KeyStore):
    """Self-host: plaintext keys from SPEECHROUTER_KEYS, hashed at boot."""

    def __init__(self, keys: str):
        self._by_hash = {
            _hash(k): KeyRecord(key_id=f"local-{i}")
            for i, k in enumerate(p.strip() for p in keys.split(",") if p.strip())
        }
        if not self._by_hash:
            logger.warning("LocalKeyStore has no keys configured; all requests will be rejected")

    async def lookup(self, presented_key: str) -> KeyRecord | None:
        return self._by_hash.get(_hash(presented_key))


def build_keystore(cfg: Settings) -> KeyStore:
    match cfg.keystore:
        case KeyStoreKind.none:
            return NoAuthKeyStore()
        case KeyStoreKind.local:
            return LocalKeyStore(cfg.keys)
        case KeyStoreKind.cloud:
            from .cloud_store import CloudKeyStore  # noqa: PLC0415 - optional path

            return CloudKeyStore(cfg.redis_url)
