"""Model catalog: merged providers/*/models.json, served by GET /v1/models."""

import json
from pathlib import Path

_PROVIDERS_DIR = Path(__file__).parent.parent / "providers"


class Catalog:
    def __init__(self, entries: list[dict]):
        self._entries = entries
        self._by_slug = {e["slug"]: e for e in entries}

    # native-unit rate field -> seconds per unit (for the derived legacy field)
    _PER_SECOND_DIVISOR = {
        "per_audio_second_usd": 1,
        "per_audio_minute_usd": 60,
        "per_audio_hour_usd": 3600,
        "per_session_hour_usd": 3600,
    }

    @classmethod
    def load(cls) -> "Catalog":
        entries: list[dict] = []
        for path in sorted(_PROVIDERS_DIR.glob("*/models.json")):
            entries.extend(json.loads(path.read_text()))
        for entry in entries:
            cls._derive_legacy_pricing(entry)
        return cls(entries)

    @classmethod
    def _derive_legacy_pricing(cls, entry: dict) -> None:
        """Inject deprecated pricing.per_second_usd so pre-v2 consumers keep
        working. Authored pricing stays in native vendor units."""
        pricing = entry.get("pricing") or {}
        for field, divisor in cls._PER_SECOND_DIVISOR.items():
            if field in pricing:
                pricing["per_second_usd"] = pricing[field] / divisor
                return

    def find(self, slug: str) -> dict | None:
        return self._by_slug.get(slug)

    def all(self) -> list[dict]:
        return self._entries
