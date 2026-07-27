"""Model catalog: merged providers/*/models.json, served by GET /v1/models."""

import json
from pathlib import Path

_PROVIDERS_DIR = Path(__file__).parent.parent / "providers"


class Catalog:
    def __init__(self, entries: list[dict]):
        self._entries = entries
        self._by_slug = {e["slug"]: e for e in entries}

    @classmethod
    def load(cls) -> "Catalog":
        entries: list[dict] = []
        for path in sorted(_PROVIDERS_DIR.glob("*/models.json")):
            entries.extend(json.loads(path.read_text()))
        return cls(entries)

    def find(self, slug: str) -> dict | None:
        return self._by_slug.get(slug)

    def all(self) -> list[dict]:
        return self._entries
