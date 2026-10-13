#!/usr/bin/env python3
"""Live TTS probe across every provider that has a key (PLAN-tts-live.md phase 2).

Runs each keyed provider's REAL gateway adapter (resolver -> TTSRun -> vendor)
with one short synthetic sentence per probed model, and records what came back:
bytes, decoded duration, time to first byte, reported usage, errors. Providers
without a key are listed as skipped (mock-tested only).

    uv run --project gateway python scripts/tts_provider_probe.py \
        --env-file /home/agent/agent-env/speechrouter-providers.env --out /tmp/tts-probe

Spend control: one ~60-character sentence per model and at most MAX_MODELS per
provider. At the most expensive list price in the catalog (~$300 per 1M chars)
that is about $0.02 per call; a full run is well under $1.

Keys are read from the env file into Settings and never printed or written.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from speechrouter_gateway import providers as _providers  # noqa: E402,F401  (registers adapters)
from speechrouter_gateway.config import Settings  # noqa: E402
from speechrouter_gateway.router.catalog import Catalog  # noqa: E402
from speechrouter_gateway.router.resolver import TTSRequest, resolve_tts  # noqa: E402
from speechrouter_gateway.tts.runner import TTSRun, list_cost, tts_units  # noqa: E402

TEXT = "Hello from the SpeechRouter probe. This is a short test."
MAX_MODELS = 2

# env-file variable -> Settings field
ENV_TO_SETTING = {
    "OPENAI_API_KEY": "openai_api_key",
    "GEMINI_API_KEY": "gemini_api_key",
    "ELEVENLABS_API_KEY": "elevenlabs_api_key",
    "CARTESIA_API_KEY": "cartesia_api_key",
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "AZURE_SPEECH_KEY": "azure_speech_key",
    "AZURE_SPEECH_REGION": "azure_speech_region",
    "GOOGLE_CLOUD_TTS_KEY": "google_tts_api_key",
    "RIME_API_KEY": "rime_api_key",
    "HUME_API_KEY": "hume_api_key",
    "LMNT_API_KEY": "lmnt_api_key",
    "INWORLD_API_KEY": "inworld_api_key",
    "FISH_AUDIO_API_KEY": "fishaudio_api_key",
    "PLAYHT_API_KEY": "playht_api_key",
    "PLAYHT_USER_ID": "playht_user_id",
    "GROQ_API_KEY": "groq_api_key",
    "MINIMAX_API_KEY": "minimax_api_key",
    "SPEECHMATICS_API_KEY": "speechmatics_api_key",
    "MURF_API_KEY": "murf_api_key",
    "RESEMBLE_API_KEY": "resemble_api_key",
}

# provider -> Settings field that must be set for it to be probed
PROVIDER_KEY = {
    "openai": "openai_api_key", "gemini": "gemini_api_key", "elevenlabs": "elevenlabs_api_key",
    "cartesia": "cartesia_api_key", "deepgram": "deepgram_api_key",
    "azure": "azure_speech_key", "google": "google_tts_api_key", "rime": "rime_api_key",
    "hume": "hume_api_key", "lmnt": "lmnt_api_key", "inworld": "inworld_api_key",
    "fishaudio": "fishaudio_api_key", "playht": "playht_api_key", "groq": "groq_api_key",
    "minimax": "minimax_api_key", "speechmatics": "speechmatics_api_key",
    "murf": "murf_api_key", "resemble": "resemble_api_key",
}


def load_env(path: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.removeprefix("export ").partition("=")
            value = value.strip().strip("'\"")
            if value:
                values[key.strip()] = value
    for key in ENV_TO_SETTING:  # the process env may also carry them
        if os.environ.get(key) and key not in values:
            values[key] = os.environ[key]
    return values


async def probe(slug: str, settings: Settings, catalog: Catalog) -> dict:
    entry = catalog.find(slug) or {}
    fmt = "pcm" if "pcm" in (entry.get("capabilities") or {}).get("formats", []) else None
    resolved = resolve_tts(slug, TTSRequest(text_length=len(TEXT), format=fmt), settings,
                           catalog)
    adapter = resolved.build()
    run = TTSRun(resolved)
    started = time.monotonic()
    first = None
    size = 0
    try:
        async for chunk in run.stream(adapter, TEXT):
            first = first or time.monotonic() - started
            size += len(chunk)
    finally:
        await adapter.close()
    units = tts_units(resolved.entry, run.usage, produced=run.produced_bytes > 0)
    return {
        "ok": size > 0, "format": resolved.out_format, "voice": resolved.config.voice,
        "bytes": size, "audio_seconds": round(run.audio_seconds, 3),
        "ttfb_ms": round((first or 0) * 1000), "total_ms": round((time.monotonic() - started)
                                                                 * 1000),
        "units": units, "estimated": run.usage.estimated,
        "list_cost_usd": list_cost(resolved.entry, units, False),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="/home/agent/agent-env/speechrouter-providers.env")
    parser.add_argument("--out", type=Path, default=Path("/tmp/tts-provider-probe"))
    parser.add_argument("--only", default="", help="comma-separated provider ids")
    args = parser.parse_args()
    env = load_env(args.env_file)
    fields = {ENV_TO_SETTING[k]: v for k, v in env.items() if k in ENV_TO_SETTING}
    settings = Settings(_env_file=None, **fields)
    catalog = Catalog.load()
    only = {p for p in args.only.split(",") if p}

    by_provider: dict[str, list[str]] = {}
    for entry in catalog.all():
        if entry["kind"] == "tts" and not entry.get("deprecated"):
            by_provider.setdefault(entry["provider"], []).append(entry["slug"])

    results: dict = {}
    total = 0.0
    for provider, slugs in sorted(by_provider.items()):
        if only and provider not in only:
            continue
        if not getattr(settings, PROVIDER_KEY.get(provider, ""), ""):
            results[provider] = {"status": "skipped: no key (mock-tested only)"}
            continue
        results[provider] = {"status": "live", "models": {}}
        for slug in slugs[:MAX_MODELS]:
            try:
                outcome = await probe(slug, settings, catalog)
            except Exception as exc:  # noqa: BLE001 - record and continue
                outcome = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            total += outcome.get("list_cost_usd", 0.0)
            results[provider]["models"][slug] = outcome
            print(f"{slug:<48} {json.dumps(outcome)[:220]}", flush=True)
    results["_estimated_spend_usd"] = round(total, 4)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(results, indent=2))
    live = [p for p, r in results.items() if isinstance(r, dict) and r.get("status") == "live"]
    print(f"live: {live or 'none'}; estimated list spend ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
