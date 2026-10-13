"""Model catalog: merged providers/*/models.json, served by GET /v1/models.

Two pricing shapes coexist:
- STT: exactly one seconds-based rate (per_audio_*, per_session_hour) priced
  against billed_seconds. The legacy per_second_usd is derived for these.
- TTS / live: one or more unit rates (per_character_usd, per_1m_*_tokens_usd)
  priced against UsageEvent.units. No per_second_usd is derived — a legacy
  consumer must see these as unpriced, never mispriced.

Dated prices (`pricing_schedule`) let a vendor's announced price change land
on its date without a deploy. Contract: PLAN-tts-live.md §3.0.
"""

import copy
import json
import time
from datetime import UTC, datetime
from pathlib import Path

_PROVIDERS_DIR = Path(__file__).parent.parent / "providers"

# UsageEvent.units key -> (catalog rate field, units per priced quantity)
UNIT_RATE_FIELDS: dict[str, tuple[str, float]] = {
    "characters": ("per_character_usd", 1.0),
    "text_input_tokens": ("per_1m_text_input_tokens_usd", 1e6),
    "cached_text_input_tokens": ("per_1m_cached_text_input_tokens_usd", 1e6),
    "audio_input_tokens": ("per_1m_audio_input_tokens_usd", 1e6),
    "cached_audio_input_tokens": ("per_1m_cached_audio_input_tokens_usd", 1e6),
    "image_input_tokens": ("per_1m_image_input_tokens_usd", 1e6),
    "text_output_tokens": ("per_1m_text_output_tokens_usd", 1e6),
    "audio_output_tokens": ("per_1m_audio_output_tokens_usd", 1e6),
}


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def effective_pricing(entry: dict, at: float | None = None) -> dict:
    """The rate set in force at `at` (unix seconds, default now)."""
    day = _date(time.time() if at is None else at)
    current = entry.get("pricing") or {}
    for step in sorted(entry.get("pricing_schedule") or [], key=lambda s: s["effective_from"]):
        if step["effective_from"] <= day:
            current = step["pricing"]
    return current


def price_units(entry: dict, units: dict[str, float], at: float | None = None) -> float:
    """Σ units × rate in USD. Units without a rate on this model cost 0."""
    pricing = effective_pricing(entry, at)
    total = 0.0
    for key, count in units.items():
        spec = UNIT_RATE_FIELDS.get(key)
        if spec is None or not count:
            continue
        rate = pricing.get(spec[0])
        if rate:
            total += count * rate / spec[1]
    return total


class Catalog:
    def __init__(self, entries: list[dict], disabled_kinds: frozenset[str] = frozenset()):
        self._entries = entries
        self._by_slug = {e["slug"]: e for e in entries}
        self._disabled = disabled_kinds

    # native-unit rate field -> seconds per unit (for the derived legacy field)
    _PER_SECOND_DIVISOR = {
        "per_audio_second_usd": 1,
        "per_audio_minute_usd": 60,
        "per_audio_hour_usd": 3600,
        "per_session_hour_usd": 3600,
    }

    @classmethod
    def load(cls, disabled_kinds: frozenset[str] = frozenset()) -> "Catalog":
        entries: list[dict] = []
        for path in sorted(_PROVIDERS_DIR.glob("*/models.json")):
            entries.extend(json.loads(path.read_text()))
        for entry in entries:
            entry.setdefault("kind", "stt")
            cls._derive_legacy_pricing(entry)
        return cls(entries, disabled_kinds)

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
        """Lookup that honours feature flags: a disabled kind does not exist."""
        entry = self._by_slug.get(slug)
        if entry is None or entry.get("kind", "stt") in self._disabled:
            return None
        return entry

    def all(self) -> list[dict]:
        return [e for e in self._entries if e.get("kind", "stt") not in self._disabled]

    def public(self) -> list[dict]:
        """GET /v1/models view: `pricing` is the rate set in force right now."""
        out = []
        for entry in self.all():
            if entry.get("pricing_schedule"):
                entry = copy.deepcopy(entry)
                entry["pricing"] = effective_pricing(entry)
            out.append(entry)
        return out
