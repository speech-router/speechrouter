#!/usr/bin/env python3
"""Dev smoke client: stream a WAV file through WSS /v1/listen and print events.

Usage:
    uv run --project gateway python scripts/stream_wav.py audio.wav \
        --model deepgram/nova-3 [--url ws://localhost:8080] [--api-key sk_...] \
        [--realtime] [--fallbacks soniox/stt-rt-v5]

Without --realtime the file is pushed as fast as the server accepts it
(the file-over-WS batch mode); with it, chunks are paced at 1x for
providers that enforce realtime pacing.
"""

import argparse
import asyncio
import json
import sys
import time
import wave

import websockets

CHUNK_MS = 100


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", default="ws://localhost:8080")
    parser.add_argument("--api-key", default="sk_local_dev")
    parser.add_argument("--fallbacks", default="")
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--diarization", action="store_true")
    args = parser.parse_args()

    with wave.open(args.wav, "rb") as f:
        if f.getsampwidth() != 2:
            print("expected 16-bit PCM wav", file=sys.stderr)
            return 1
        sample_rate = f.getframerate()
        channels = f.getnchannels()
        audio = f.readframes(f.getnframes())

    frames_per_chunk = int(sample_rate * CHUNK_MS / 1000)
    chunk_bytes = frames_per_chunk * 2 * channels
    query = (
        f"model={args.model}&encoding=linear16&sample_rate={sample_rate}"
        f"&channels={channels}&api_key={args.api_key}"
    )
    if args.fallbacks:
        query += f"&fallbacks={args.fallbacks}"
    if args.diarization:
        query += "&diarization=true"
    url = f"{args.url}/v1/listen?{query}"

    started = time.monotonic()
    async with websockets.connect(url) as ws:

        async def send() -> None:
            for i in range(0, len(audio), chunk_bytes):
                await ws.send(audio[i : i + chunk_bytes])
                if args.realtime:
                    await asyncio.sleep(CHUNK_MS / 1000)
            await ws.send(json.dumps({"type": "finalize"}))

        async def receive() -> None:
            async for raw in ws:
                event = json.loads(raw)
                kind = event["type"]
                if kind == "transcript":
                    marker = "F" if event["is_final"] else "…"
                    print(f"[{marker}] {event['text']}")
                elif kind == "done":
                    print(f"done: {event['usage']}")
                    return
                elif kind == "error":
                    print(f"ERROR {event['code']}: {event['message']}", file=sys.stderr)
                    return
                else:
                    print(f"({kind}) {json.dumps({k: v for k, v in event.items() if k != 'type'})}")

        await asyncio.gather(send(), receive())
    print(f"elapsed: {time.monotonic() - started:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
