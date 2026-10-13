#!/usr/bin/env python3
"""Capture real OpenAI / Gemini TTS + live wire frames and settle the open
metering questions in PLAN-tts-live.md (§2.6, §6). Talks DIRECTLY to the
vendors, not through the gateway: the point is untouched payloads that
become test fixtures.

Usage:
    # keys from the environment or an env file; never pass them as argv
    uv run --project gateway python scripts/tts_live_probe.py \
        --env-file /home/agent/agent-env/speechrouter-providers.env --out /tmp/probe

Experiments (each tiny; the whole run is well under $0.50 at list price):
    openai_tts      gpt-4o-mini-tts SSE: event shapes + speech.audio.done usage
                    -> audio tokens per second (OpenAITTS.AUDIO_TOKENS_PER_SECOND)
    gemini_tts      gemini-3.8-flash-tts SSE: inlineData + usageMetadata (cumulative?)
    openai_live     gpt-realtime-2.1-mini, one 1 s audio turn: response.done usage
                    -> realtime audio tokens per second in/out (meter estimates)
    gemini_live     gemini-3.8-live, TWO turns: is usageMetadata per turn or
                    cumulative? (settings.gemini_live_usage_semantics)

Output: <out>/<exp>.jsonl (frames, base64 audio truncated) and summary.json.
Keys are never written or printed.
"""

import argparse
import array
import asyncio
import base64
import json
import math
import os
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _scrub import scrub  # noqa: E402

SECRETS: list[str] = []  # every value loaded from the env file; scrubbed from all output

TEXT = "This is a short synthetic probe sentence for metering."


def load_env(path: str | None) -> None:
    if not path:
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip().strip("'\"")
        if value:
            SECRETS.append(value)
        os.environ.setdefault(key.strip(), value)


def save_wav(path: Path, pcm: bytes, rate: int = 24000) -> None:
    import struct

    header = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
              + b"data" + struct.pack("<I", len(pcm)))
    path.write_bytes(header + pcm)


def tone(seconds: float, rate: int) -> bytes:
    return array.array("h", [int(4000 * math.sin(2 * math.pi * 220 * i / rate))
                             for i in range(int(seconds * rate))]).tobytes()


def redact(obj):
    """Truncate base64 audio so fixtures stay small; keys never appear."""
    if isinstance(obj, dict):
        return {k: (v[:32] + f"…<{len(v)} chars>" if k in {"data", "audio", "delta"}
                    and isinstance(v, str) and len(v) > 64 else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class Recorder:
    def __init__(self, out: Path, name: str):
        self.file = (out / f"{name}.jsonl").open("w")
        self.t0 = time.monotonic()

    def write(self, direction: str, payload) -> None:
        line = json.dumps({"t": round(time.monotonic() - self.t0, 3),
                           "dir": direction, "frame": redact(payload)})
        self.file.write(scrub(line, SECRETS) + "\n")
        self.file.flush()


async def openai_tts(out: Path) -> dict:
    rec = Recorder(out, "openai_tts")
    key = os.environ["OPENAI_API_KEY"]
    body = {"model": "gpt-4o-mini-tts", "voice": "coral", "input": TEXT,
            "response_format": "pcm", "stream_format": "sse"}
    audio = 0
    pcm_out: list[bytes] = []
    usage = None
    async with httpx.AsyncClient(timeout=60) as client, client.stream(
        "POST", "https://api.openai.com/v1/audio/speech", json=body,
        headers={"Authorization": f"Bearer {key}"},
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            event = json.loads(line[5:])
            rec.write("down", event)
            if event.get("type") == "speech.audio.delta":
                pcm_out.append(base64.b64decode(event["audio"]))
                audio += len(pcm_out[-1])
            elif event.get("type") == "speech.audio.done":
                usage = event.get("usage")
    seconds = audio / 48000
    save_wav(out / "openai__gpt-4o-mini-tts.wav", b"".join(pcm_out))
    return {"audio_seconds": round(seconds, 3), "usage": usage,
            "audio_tokens_per_second": round((usage or {}).get("output_tokens", 0) / seconds, 2)
            if seconds else None}


async def gemini_tts(out: Path) -> dict:
    rec = Recorder(out, "gemini_tts")
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"role": "user", "parts": [{"text": TEXT}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}}
    audio = 0
    pcm_out: list[bytes] = []
    usages = []
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-3.8-flash-tts:streamGenerateContent?alt=sse")
    async with httpx.AsyncClient(timeout=60) as client, client.stream(
        "POST", url, json=body, headers={"x-goog-api-key": key}
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            chunk = json.loads(line[5:])
            rec.write("down", chunk)
            for cand in chunk.get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    if part.get("inlineData"):
                        pcm_out.append(base64.b64decode(part["inlineData"]["data"]))
                        audio += len(pcm_out[-1])
            if chunk.get("usageMetadata"):
                usages.append(chunk["usageMetadata"])
    seconds = audio / 48000
    last = usages[-1] if usages else {}
    save_wav(out / "gemini__gemini-3.8-flash-tts.wav", b"".join(pcm_out))
    return {"audio_seconds": round(seconds, 3), "usage_messages": len(usages),
            "usage_last": last, "audio_tokens_per_second": round(
                last.get("candidatesTokenCount", 0) / seconds, 2) if seconds else None}


async def openai_live(out: Path) -> dict:
    rec = Recorder(out, "openai_live")
    key = os.environ["OPENAI_API_KEY"]
    url = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
    out_audio = 0
    usage = None
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {key}"},
                                  max_size=16 * 1024 * 1024) as ws:
        async def send(event):
            rec.write("up", event)
            await ws.send(json.dumps(event))

        await send({"type": "session.update", "session": {
            "type": "realtime", "output_modalities": ["audio"],
            "instructions": "Reply with one short sentence.",
            "audio": {"input": {"turn_detection": None}}}})
        pcm = tone(1.0, 24000)
        await send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})
        await send({"type": "input_audio_buffer.commit"})
        await send({"type": "response.create"})
        async with asyncio.timeout(60):
            async for raw in ws:
                event = json.loads(raw)
                rec.write("down", event)
                if event.get("type") in ("response.output_audio.delta", "response.audio.delta"):
                    out_audio += len(base64.b64decode(event["delta"]))
                if event.get("type") == "response.done":
                    usage = event["response"].get("usage")
                    break
                if event.get("type") == "error":
                    return {"error": event.get("error")}
    details = (usage or {}).get("input_token_details") or {}
    out_details = (usage or {}).get("output_token_details") or {}
    out_seconds = out_audio / 48000
    return {"usage": usage, "audio_in_seconds": 1.0, "audio_out_seconds": round(out_seconds, 3),
            "in_audio_tokens_per_second": details.get("audio_tokens"),
            "out_audio_tokens_per_second": round(out_details.get("audio_tokens", 0) / out_seconds,
                                                 2) if out_seconds else None}


async def gemini_live(out: Path) -> dict:
    rec = Recorder(out, "gemini_live")
    key = os.environ["GEMINI_API_KEY"]
    url = ("wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta"
           ".GenerativeService.BidiGenerateContent")
    usages: list[list[dict]] = []
    async with websockets.connect(url, additional_headers={"x-goog-api-key": key},
                                  max_size=16 * 1024 * 1024) as ws:
        async def send(msg):
            rec.write("up", msg)
            await ws.send(json.dumps(msg))

        await send({"setup": {"model": "models/gemini-3.8-live", "generationConfig": {
            "responseModalities": ["AUDIO"]},
            "systemInstruction": {"parts": [{"text": "Answer in one short sentence."}]}}})
        rec.write("down", json.loads(await ws.recv()))
        for turn in range(2):
            usages.append([])
            await send({"clientContent": {"turns": [{"role": "user", "parts": [
                {"text": f"Say the number {turn + 1}."}]}], "turnComplete": True}})
            async with asyncio.timeout(60):
                async for raw in ws:
                    msg = json.loads(raw)
                    rec.write("down", msg)
                    if msg.get("usageMetadata"):
                        usages[-1].append(msg["usageMetadata"])
                    if (msg.get("serverContent") or {}).get("turnComplete"):
                        break
    totals = [[u.get("totalTokenCount") for u in turn] for turn in usages]
    # No automatic verdict: per-turn reports also grow (each turn re-bills the
    # context), so growth alone can't distinguish the two. Compare the summed
    # vs last totals against the billing console for this run.
    return {"usage_per_turn": usages, "total_token_counts": totals,
            "sum_of_all_reports": sum(t or 0 for turn in totals for t in turn),
            "last_report_total": (totals[-1] or [None])[-1] if totals else None,
            "note": "per_message => billing ~= sum_of_all_reports; "
                    "cumulative => billing ~= last_report_total"}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file")
    parser.add_argument("--out", type=Path, default=Path("/tmp/tts-live-probe"))
    parser.add_argument("--exp", default="all",
                        choices=["all", "openai_tts", "gemini_tts", "openai_live", "gemini_live"])
    args = parser.parse_args()
    load_env(args.env_file)
    args.out.mkdir(parents=True, exist_ok=True)
    experiments = {"openai_tts": openai_tts, "gemini_tts": gemini_tts,
                   "openai_live": openai_live, "gemini_live": gemini_live}
    summary = {}
    for name, run in experiments.items():
        if args.exp not in ("all", name):
            continue
        needs = "OPENAI_API_KEY" if name.startswith("openai") else "GEMINI_API_KEY"
        if not os.environ.get(needs):
            summary[name] = {"skipped": f"{needs} not set"}
            continue
        try:
            summary[name] = await run(args.out)
        except Exception as exc:  # noqa: BLE001 - record and continue
            summary[name] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        print(scrub(f"{name} {json.dumps(summary[name])[:600]}", SECRETS), flush=True)
    (args.out / "summary.json").write_text(scrub(json.dumps(summary, indent=2), SECRETS))


if __name__ == "__main__":
    asyncio.run(main())
