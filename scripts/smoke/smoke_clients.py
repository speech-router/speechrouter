#!/usr/bin/env python3
"""TTS + live smoke test through a LOCAL gateway, driven by the official SDKs.

  1. POST /v1/audio/speech (streaming)  — OpenAI Python SDK, openai + gemini models
  2. WSS  /v1/speak                     — raw websockets (our protocol; no vendor SDK)
  3. OpenAI Realtime passthrough        — OpenAI SDK `client.realtime.connect`
  4. Gemini Live passthrough            — google-genai `client.aio.live.connect`
  5. Usage events                       — read from the gateway's log emitter (the
                                          same payload the Redis emitter XADDs) and
                                          checked against PLAN §3.0

Point it at a gateway started by scripts/smoke/run_smoke.sh. The gateway key
comes from SMOKE_GATEWAY_KEY (a local throwaway key, never a provider key).
Writes <out>/smoke-report.json, audio samples, and a readable log.
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

V2_FIELDS = {
    "session_id", "key_id", "model", "kind", "audio_seconds", "billed_seconds",
    "billing_basis", "characters", "provider_switches", "status", "byok", "ts", "units",
    "units_estimated", "parent_session_id", "session_seconds", "output_audio_seconds",
    "list_cost_usd",
}
PHASE2 = ["elevenlabs", "cartesia", "deepgram", "azure", "google", "rime", "inworld",
          "fishaudio", "minimax", "groq", "murf", "speechmatics",
          "xai", "aws", "mistral", "smallest", "together"]
UNIT_KEYS = {"utf8_bytes", "cached_image_input_tokens",
             "characters", "text_input_tokens", "cached_text_input_tokens",
             "audio_input_tokens", "cached_audio_input_tokens", "image_input_tokens",
             "text_output_tokens", "audio_output_tokens"}


def tone(seconds: float, rate: int) -> bytes:
    return array.array("h", [int(5000 * math.sin(2 * math.pi * 200 * i / rate))
                             for i in range(int(seconds * rate))]).tobytes()


class Report:
    def __init__(self, out: Path):
        self.out = out
        self.results: dict = {}
        self.log_lines: list[str] = []

    def log(self, line: str) -> None:
        print(line, flush=True)
        self.log_lines.append(line)

    def check(self, name: str, ok: bool, **detail) -> None:
        self.results[name] = {"ok": bool(ok), **detail}
        self.log(f"[{'PASS' if ok else 'FAIL'}] {name} {json.dumps(detail, default=str)}")


# ---------------------------------------------------------------- 1. TTS


def tts_rest(base: str, key: str, report: Report) -> None:
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url=f"{base}/v1")
    cases = [
        ("openai/gpt-4o-mini-tts", "coral", "wav", "tts-openai-mini.wav"),
        ("openai/tts-1", "alloy", "pcm", "tts-openai-tts1.pcm"),
        ("gemini/gemini-3.8-flash-tts", "Puck", "wav", "tts-gemini-flash.wav"),
        ("gemini/gemini-3.8-flash-lite-tts", "Kore", "mulaw", "tts-gemini-lite.ulaw"),
    ]
    # phase 2: one model per provider, default voice, through the same SDK call
    for slug in ["elevenlabs/eleven_flash_v2_5", "cartesia/sonic-3.6", "deepgram/aura-2",
                 "azure/neural", "google/chirp3-hd", "rime/coda", "inworld/inworld-tts-2",
                 "fishaudio/s2.1-pro", "minimax/speech-2.8-turbo", "groq/orpheus-v1-english",
                 "murf/falcon-2", "speechmatics/preview",
                 # phase 3
                 "xai/grok-tts", "deepgram/flux", "aws/polly-neural",
                 "mistral/voxtral-mini-tts-2603", "smallest/lightning_v3.1",
                 "together/kokoro-82m"]:
        cases.append((slug, None, "wav", f"tts-{slug.replace('/', '-')}.wav"))
    for model, voice, fmt, filename in cases:
        started = time.monotonic()
        first_at = None
        chunks = 0
        data = b""
        extra = {"voice": voice}  # None -> JSON null -> the model's default voice
        with client.audio.speech.with_streaming_response.create(
            model=model, response_format=fmt, **extra,  # type: ignore[arg-type]
            input="Hello from the SpeechRouter smoke test. This sentence is synthetic.",
        ) as response:
            headers = dict(response.headers)
            for chunk in response.iter_bytes():
                if first_at is None:
                    first_at = time.monotonic() - started
                chunks += 1
                data += chunk
        (report.out / filename).write_bytes(data)
        ok = len(data) > 1000 and (fmt != "wav" or data[:4] == b"RIFF")
        report.check(f"tts_rest:{model}:{fmt}", ok, bytes=len(data), http_chunks=chunks,
                     ttfb_ms=round((first_at or 0) * 1000), content_type=headers.get(
                         "content-type"), request_id=headers.get("x-speechrouter-request-id"))


# ---------------------------------------------------------------- 2. speak


async def speak_ws(ws_base: str, key: str, report: Report, ssl_ctx) -> None:
    url = f"{ws_base}/v1/speak?model=openai/gpt-4o-mini-tts&voice=marin&encoding=linear16"
    frames: list[str] = []
    audio = b""
    async with websockets.connect(url, subprotocols=["bearer", key], ssl=ssl_ctx) as ws:
        opened = json.loads(await ws.recv())
        tokens = ["Thanks for calling. ", "Your appointment ", "is confirmed for ",
                  "Tuesday at ten. ", "Is there anything ", "else I can help with?"]
        for token in tokens:
            await ws.send(json.dumps({"type": "text.delta", "text": token}))
            await asyncio.sleep(0.05)  # LLM-like token pacing
        await ws.send(json.dumps({"type": "finalize"}))
        done = None
        while done is None:
            message = await ws.recv()
            if isinstance(message, bytes):
                audio += message
                frames.append("bytes")
                continue
            event = json.loads(message)
            frames.append(event["type"])
            if event["type"] == "done":
                done = event
            elif event["type"] == "error":
                raise RuntimeError(event)
    (report.out / "speak-openai-mini.pcm").write_bytes(audio)
    paired = all(frames[i] == "audio.chunk" and frames[i + 1] == "bytes"
                 for i in range(0, len(frames) - 1, 2))
    report.check("speak_ws:openai/gpt-4o-mini-tts", paired and len(audio) > 0,
                 session=opened.get("session_id"), audio_chunks=frames.count("bytes"),
                 pcm_seconds=round(len(audio) / 48000, 3), done_usage=done["usage"])


async def speak_native(ws_base: str, key: str, report: Report, ssl_ctx, slug: str,
                       encoding: str) -> None:
    """/v1/speak over a provider-native socket, with a barge-in mid-stream."""
    url = f"{ws_base}/v1/speak?model={slug}&encoding={encoding}"
    events: list[dict] = []
    audio = b""
    async with websockets.connect(url, subprotocols=["bearer", key], ssl=ssl_ctx) as ws:
        events.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "text.delta", "text": "Your table is ready now. "}))
        first = await ws.recv()  # audio.chunk
        events.append(json.loads(first))
        audio += await ws.recv()
        await ws.send(json.dumps({"type": "clear", "playback_ms": 120}))
        await ws.send(json.dumps({"type": "text.delta", "text": "Sorry, go ahead."}))
        await ws.send(json.dumps({"type": "finalize"}))
        while True:
            frame = await ws.recv()
            if isinstance(frame, bytes):
                audio += frame
                continue
            event = json.loads(frame)
            events.append(event)
            if event["type"] in ("done", "error"):
                break
    cleared = next((e for e in events if e["type"] == "cleared"), None)
    done = events[-1]
    ok = cleared is not None and done["type"] == "done" and len(audio) > 0
    if slug == "deepgram/flux":
        ok = ok and "text_spoken" in (cleared or {})
    report.check(f"speak_native:{slug}:{encoding}", ok, cleared=cleared,
                 audio_bytes=len(audio), done_usage=done.get("usage"))


# ---------------------------------------------------------------- 3. OpenAI


async def openai_realtime(base: str, key: str, report: Report) -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, base_url=f"{base}/v1")
    seen_types: list[str] = []
    async with client.realtime.connect(model="openai/gpt-realtime-2.1") as conn:
        await conn.session.update(session={
            "type": "realtime",
            "audio": {"input": {"transcription": {"model": "gpt-4o-mini-transcribe"}}},
        })
        pcm = tone(1.0, 24000)
        for i in range(0, len(pcm), 9600):
            await conn.input_audio_buffer.append(audio=base64.b64encode(pcm[i:i + 9600]).decode())
        await conn.response.create()
        async for event in conn:
            seen_types.append(event.type)
            if event.type == "response.done":
                usage = event.response.usage
                break
    report.check("live:openai-realtime:sdk", "response.done" in seen_types,
                 events=sorted(set(seen_types)),
                 usage_input_tokens=getattr(usage, "input_tokens", None))


# ---------------------------------------------------------------- 4. Gemini


async def gemini_live(base: str, key: str, report: Report) -> None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key,
                          http_options=types.HttpOptions(base_url=base, api_version="v1beta"))
    received = 0
    audio_bytes = 0
    turn_complete = False
    usage = None
    config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])
    async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
        pcm = tone(1.0, 16000)
        for i in range(0, len(pcm), 3200):
            await session.send_realtime_input(
                audio=types.Blob(data=pcm[i:i + 3200], mime_type="audio/pcm;rate=16000"))
        await session.send_realtime_input(audio_stream_end=True)
        async for message in session.receive():
            received += 1
            if message.data:
                audio_bytes += len(message.data)
            if message.usage_metadata:
                usage = message.usage_metadata.prompt_token_count
            if message.server_content and message.server_content.turn_complete:
                turn_complete = True
                break
    report.check("live:gemini-live:sdk", turn_complete and audio_bytes > 0,
                 messages=received, audio_out_seconds=round(audio_bytes / 48000, 3),
                 usage_prompt_tokens=usage)


# ---------------------------------------------------------------- 5. usage


def check_usage(gateway_log: Path, mock_base: str, report: Report) -> None:
    events = []
    for line in gateway_log.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("msg") == "usage":
            # what RedisUsageEmitter XADDs: {"payload": json.dumps(asdict(event))}
            events.append(json.loads(json.dumps(record["usage"])))
    (report.out / "usage-events.json").write_text(json.dumps(events, indent=2))
    report.log(f"usage events: {len(events)}")
    for event in events:
        report.log(f"  {event['kind']:<10} {event['model']:<34} {event['session_id']:<28} "
                   f"status={event['status']:<11} units={event['units']} "
                   f"cost=${event['list_cost_usd']:.6f}")
    schema_ok = all(set(e) == V2_FIELDS for e in events)
    units_ok = all(set(e["units"]) <= UNIT_KEYS for e in events)
    kinds = sorted({e["kind"] for e in events})
    report.check("usage:schema_v2_exact_fields", schema_ok and units_ok, events=len(events),
                 kinds=kinds)
    phase2 = {e["model"].split("/")[0]: e for e in events if e["kind"] == "tts_batch"}
    fish = phase2.get("fishaudio", {})
    report.check("usage:fish_bills_utf8_bytes", set(fish.get("units", {})) == {"utf8_bytes"},
                 units=fish.get("units"))
    report.check("usage:phase2_providers_all_metered",
                 all(phase2.get(p, {}).get("list_cost_usd", 0) > 0 for p in PHASE2),
                 missing=[p for p in PHASE2 if p not in phase2])
    report.check("usage:all_kinds_present",
                 {"tts_batch", "tts_stream", "live", "stt_stream"} <= set(kinds), kinds=kinds)
    unique = len({e["session_id"] for e in events}) == len(events)
    report.check("usage:session_ids_unique", unique)
    lives = [e for e in events if e["kind"] == "live"]
    parents_ok = all(e["parent_session_id"] and
                     e["session_id"].startswith(e["parent_session_id"] + ":") for e in lives)
    report.check("usage:live_parent_ids", parents_ok and len(lives) >= 2,
                 live_events=len(lives))
    stt = [e for e in events if e["kind"] == "stt_stream"]
    report.check("usage:openai_transcription_leg",
                 any(e["model"] == "openai/gpt-4o-mini-transcribe" and e["billed_seconds"] > 0
                     and ":t" in e["session_id"] for e in stt))
    finals = [e for e in events if e["status"] != "in_progress"]
    priced = all(e["list_cost_usd"] > 0 for e in finals)
    report.check("usage:final_events_have_cost", priced,
                 costs={e["session_id"]: e["list_cost_usd"] for e in finals})

    seen = httpx.get(f"{mock_base}/_seen").json()
    (report.out / "upstream-requests.json").write_text(json.dumps(seen, indent=2))
    report.check("upstream:only_house_credentials",
                 all(s["house_credential"] for s in seen) and not any(
                     s.get("key_in_url") for s in seen), upstream_requests=len(seen))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://127.0.0.1:8787")
    parser.add_argument("--mock", default="http://127.0.0.1:8788")
    parser.add_argument("--gateway-log", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ["SMOKE_GATEWAY_KEY"]
    args.out.mkdir(parents=True, exist_ok=True)
    report = Report(args.out)

    import ssl  # noqa: PLC0415

    ssl_ctx = ssl.create_default_context()  # trusts SSL_CERT_FILE (the smoke CA)
    ws_base = args.base.replace("https://", "wss://").replace("http://", "ws://")
    steps = [
        ("tts_rest", lambda: asyncio.to_thread(tts_rest, args.base, key, report)),
        ("speak_ws", lambda: speak_ws(ws_base, key, report, ssl_ctx)),
        ("speak_native_xai", lambda: speak_native(ws_base, key, report, ssl_ctx,
                                                  "xai/grok-tts", "mulaw")),
        ("speak_native_flux", lambda: speak_native(ws_base, key, report, ssl_ctx,
                                                   "deepgram/flux", "linear16")),
        ("openai_realtime", lambda: openai_realtime(args.base, key, report)),
        ("gemini_live", lambda: gemini_live(args.base, key, report)),
    ]
    for name, step in steps:
        try:
            await step()
        except Exception as exc:  # noqa: BLE001 - record and continue
            report.check(f"{name}:crashed", False, error=f"{type(exc).__name__}: {exc}")
    await asyncio.sleep(1.5)  # live sessions emit their final event after close
    check_usage(args.gateway_log, args.mock, report)

    passed = sum(r["ok"] for r in report.results.values())
    report.log(f"SUMMARY: {passed}/{len(report.results)} checks passed")
    (args.out / "smoke-report.json").write_text(json.dumps(report.results, indent=2))
    (args.out / "smoke-clients.log").write_text("\n".join(report.log_lines) + "\n")
    return 0 if passed == len(report.results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
