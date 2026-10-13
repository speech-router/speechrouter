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

sys.path.insert(0, str(ROOT / "scripts"))
from _scrub import scrub  # noqa: E402

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
    # phase 3
    "XAI_API_KEY": "xai_api_key",
    "MISTRAL_API_KEY": "mistral_api_key",
    "SMALLEST_API_KEY": "smallest_api_key",
    "TOGETHER_API_KEY": "together_api_key",
    # Polly is mock-only by decision (no real AWS calls); deliberately unmapped
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
    "xai": "xai_api_key", "mistral": "mistral_api_key", "smallest": "smallest_api_key",
    "together": "together_api_key",
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


def _save(audio_dir: Path | None, slug: str, fmt: str, rate: int, audio: bytes) -> str | None:
    if audio_dir is None or not audio:
        return None
    from speechrouter_gateway.audio.pcm_codec import wav_header

    audio_dir.mkdir(parents=True, exist_ok=True)
    name = slug.replace("/", "__")
    if fmt == "pcm":
        path = audio_dir / f"{name}.wav"
        path.write_bytes(wav_header(rate) + audio)
    else:
        path = audio_dir / f"{name}.{ {'mulaw': 'ulaw', 'opus': 'ogg'}.get(fmt, fmt)}"
        path.write_bytes(audio)
    return path.name


async def probe(slug: str, settings: Settings, catalog: Catalog, audio_dir: Path | None,
                fmt: str | None = None) -> dict:
    entry = catalog.find(slug) or {}
    if fmt is None:
        fmt = "pcm" if "pcm" in (entry.get("capabilities") or {}).get("formats", []) else None
    resolved = resolve_tts(slug, TTSRequest(text_length=len(TEXT), format=fmt), settings,
                           catalog)
    adapter = resolved.build()
    run = TTSRun(resolved)
    started = time.monotonic()
    first = None
    audio = b""
    try:
        async for chunk in run.stream(adapter, TEXT):
            first = first or time.monotonic() - started
            audio += chunk
    finally:
        await adapter.close()
    units = tts_units(resolved.entry, run.usage, produced=run.produced_bytes > 0)
    suffix = "" if fmt in (None, "pcm") else f"__{fmt}"
    return {
        "ok": len(audio) > 0, "format": resolved.out_format,
        "sample_rate": resolved.out_sample_rate, "voice": resolved.config.voice,
        "bytes": len(audio), "audio_seconds": round(run.audio_seconds, 3),
        "ttfb_ms": round((first or 0) * 1000),
        "total_ms": round((time.monotonic() - started) * 1000),
        # vendor-reported billed characters (when the adapter reads one) vs text length
        "text_length": len(TEXT), "billed_characters": run.usage.characters,
        "units": units, "estimated": run.usage.estimated,
        "list_cost_usd": list_cost(resolved.entry, units, False),
        "audio_file": _save(audio_dir, slug + suffix, resolved.out_format,
                            resolved.out_sample_rate, audio),
    }


async def probe_flux_socket(settings: Settings, catalog: Catalog) -> dict:
    """Native /v2/speak socket: two Speak frames, a barge-in, finish."""
    resolved = resolve_tts("deepgram/flux", TTSRequest(format="pcm"), settings, catalog)
    adapter = resolved.build()
    stream = adapter.open_stream(resolved.config)
    assert stream is not None
    audio: list[bytes] = []
    text = "Good morning. Your appointment is confirmed for Tuesday at ten."
    await stream.connect(resolved.config)

    async def collect():
        async for chunk in stream.audio():
            audio.append(chunk)

    reader = asyncio.create_task(collect())
    await stream.send_text(text)
    async with asyncio.timeout(10):
        while sum(map(len, audio)) < 48000 * 0.6:  # noqa: ASYNC110 - ~0.6 s of audio
            await asyncio.sleep(0.02)
    played_ms = 500
    info = await asyncio.wait_for(stream.clear(playback_ms=played_ms), 10)
    await stream.send_text("Sorry, go ahead.")
    await stream.finish()
    await asyncio.wait_for(reader, 20)
    await stream.close()
    sent = len(text) + len("Sorry, go ahead.")
    return {"ok": bool(audio), "interrupt": info, "text_sent_chars": sent,
            "billed_characters": stream.usage.characters,
            "audio_bytes": sum(map(len, audio))}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="/home/agent/agent-env/speechrouter-providers.env")
    parser.add_argument("--out", type=Path, default=Path("/tmp/tts-provider-probe"))
    parser.add_argument("--only", default="", help="comma-separated provider ids")
    parser.add_argument("--max-models", type=int, default=99)
    parser.add_argument("--audio-dir", type=Path, default=None)
    args = parser.parse_args()
    env = load_env(args.env_file)
    secrets = list(env.values())

    def out(line: str) -> None:
        print(scrub(line, secrets), flush=True)
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
        if provider == "aws":
            results[provider] = {"status": "skipped: mock-only by decision (no real AWS calls)"}
            continue
        if not getattr(settings, PROVIDER_KEY.get(provider, ""), ""):
            results[provider] = {"status": "skipped: no key (mock-tested only)"}
            continue
        results[provider] = {"status": "live", "models": {}}
        cases = [(slug, None) for slug in slugs[:args.max_models]]
        # the 8 kHz telephony path, natively where the provider has it
        cases += [(slugs[0], "mulaw")]
        for slug, fmt in cases:
            label = slug if fmt is None else f"{slug} [{fmt}]"
            try:
                outcome = await probe(slug, settings, catalog, args.audio_dir, fmt)
            except Exception as exc:  # noqa: BLE001 - record and continue
                outcome = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
            total += outcome.get("list_cost_usd", 0.0)
            results[provider]["models"][label] = outcome
            out(f"{label:<48} {json.dumps(outcome)[:260]}")
        if provider == "deepgram":
            try:
                results[provider]["flux_native_socket"] = await probe_flux_socket(settings,
                                                                                  catalog)
            except Exception as exc:  # noqa: BLE001
                results[provider]["flux_native_socket"] = {
                    "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
            socket = results[provider]["flux_native_socket"]
            out(f"deepgram/flux native socket {json.dumps(socket)}")
            total += 80 * 0.000045
    results["_estimated_spend_usd"] = round(total, 4)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(scrub(json.dumps(results, indent=2), secrets))
    live = [p for p, r in results.items() if isinstance(r, dict) and r.get("status") == "live"]
    out(f"live: {live or 'none'}; estimated list spend ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
