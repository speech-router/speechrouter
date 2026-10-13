#!/usr/bin/env python3
"""Mock OpenAI + Gemini upstream for the TTS/live smoke test (no keys needed).

Speaks just enough of each vendor's documented wire format for the gateway
to exercise its real adapters and proxy end to end:

  POST /v1/audio/speech                       OpenAI TTS (SSE for gpt-4o-mini-tts,
                                              raw bytes for tts-1*)
  POST /v1beta/models/{m}:streamGenerateContent  Gemini TTS (SSE, pcm 24k)
  WS   /v1/realtime?model=...                 OpenAI Realtime (GA event names)
  WS   /ws/google.ai...BidiGenerateContent    Gemini Live (JSON in binary frames)

Every request's credential is checked against the gateway's HOUSE key and
recorded (redacted), so the smoke run can prove the client's key never
reaches upstream. Audio is synthetic (sine tones), never real speech.

Run: uv run --project gateway python scripts/smoke/mock_upstream.py --port 8788
"""

import argparse
import array
import asyncio
import base64
import json
import math
import sys

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse

HOUSE_OPENAI = "mock-house-openai"
HOUSE_GEMINI = "mock-house-gemini"

app = FastAPI()
seen: list[dict] = []  # request log, served at GET /_seen


def tone(seconds: float, rate: int, freq: float = 330.0) -> bytes:
    n = int(seconds * rate)
    return array.array(
        "h", [int(6000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    ).tobytes()


def wav_header(data_bytes: int, rate: int = 24000) -> bytes:
    import struct  # noqa: PLC0415

    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", data_bytes))


def record(kind: str, credential: str, expected: str, **extra) -> bool:
    ok = credential == expected
    seen.append({"kind": kind, "house_credential": ok,
                 "credential_prefix": credential[:6] + "…" if credential else "", **extra})
    return ok


@app.get("/_seen")
async def get_seen() -> JSONResponse:
    return JSONResponse(seen)


# ------------------------------------------------------------- TTS


@app.post("/v1/audio/speech")
async def openai_speech(request: Request):
    auth = request.headers.get("authorization", "").removeprefix("Bearer ")
    body = await request.json()
    if not record("openai_tts", auth, HOUSE_OPENAI, model=body.get("model"),
                  stream_format=body.get("stream_format"), fmt=body.get("response_format")):
        return JSONResponse({"error": {"message": "bad key"}}, status_code=401)
    pcm = tone(0.2 + len(body["input"]) * 0.02, 24000)  # ~ speech-length audio
    if body.get("response_format") == "wav":  # real OpenAI returns a WAV file here
        pcm = wav_header(len(pcm)) + pcm
    if body.get("stream_format") == "sse":
        async def events():
            for i in range(0, len(pcm), 4800):
                chunk = base64.b64encode(pcm[i:i + 4800]).decode()
                yield f"data: {json.dumps({'type': 'speech.audio.delta', 'audio': chunk})}\n\n"
                await asyncio.sleep(0.01)
            usage = {"input_tokens": max(1, len(body["input"]) // 4),
                     "output_tokens": int(len(pcm) / 48000 * 20.8) + 1}
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            done = {"type": "speech.audio.done", "usage": usage}
            yield f"data: {json.dumps(done)}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")
    return Response(pcm, media_type="audio/L16")


@app.post("/v1beta/models/{model_action:path}")
async def gemini_generate(model_action: str, request: Request):
    key = request.headers.get("x-goog-api-key", "")
    body = await request.json()
    voice = body["generationConfig"]["speechConfig"]["voiceConfig"][
        "prebuiltVoiceConfig"]["voiceName"]
    if not record("gemini_tts", key, HOUSE_GEMINI, path=model_action,
                  key_in_url="key=" in str(request.url), voice=voice):
        return JSONResponse({"error": {"code": 403}}, status_code=403)
    text = body["contents"][0]["parts"][0]["text"]
    pcm = tone(0.2 + len(text) * 0.02, 24000, 440)

    async def events():
        step = 9600
        for i in range(0, len(pcm), step):
            chunk = {"candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000",
                "data": base64.b64encode(pcm[i:i + step]).decode()}}]}}]}
            if i + step >= len(pcm):
                chunk["usageMetadata"] = {"promptTokenCount": max(1, len(text) // 4),
                                          "candidatesTokenCount": int(len(pcm) / 48000 * 25)}
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.01)
    return StreamingResponse(events(), media_type="text/event-stream")


# ------------------------------------------------------------- live


@app.websocket("/v1/realtime")
async def openai_realtime(ws: WebSocket):
    auth = ws.headers.get("authorization", "").removeprefix("Bearer ")
    model = ws.query_params.get("model")
    await ws.accept()
    if not record("openai_realtime", auth, HOUSE_OPENAI, model=model):
        await ws.close(code=1008, reason="bad key")
        return
    session = {"id": "sess_mock", "type": "realtime", "model": model,
               "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                                   "transcription": None},
                         "output": {"format": {"type": "audio/pcm", "rate": 24000},
                                    "voice": "alloy"}}}
    await ws.send_text(json.dumps({"type": "session.created", "event_id": "e0",
                                   "session": session}))
    appended = 0
    try:
        while True:
            event = json.loads(await ws.receive_text())
            kind = event.get("type")
            if kind == "session.update":
                update = event.get("session") or {}
                transcription = ((update.get("audio") or {}).get("input") or {}).get(
                    "transcription")
                if transcription:
                    session["audio"]["input"]["transcription"] = transcription
                await ws.send_text(json.dumps({"type": "session.updated", "session": session}))
            elif kind == "input_audio_buffer.append":
                appended += len(base64.b64decode(event["audio"]))
            elif kind == "response.create":
                audio = tone(0.6, 24000, 520)
                for i in range(0, len(audio), 9600):
                    await ws.send_text(json.dumps({
                        "type": "response.output_audio.delta", "response_id": "resp_1",
                        "delta": base64.b64encode(audio[i:i + 9600]).decode()}))
                await ws.send_text(json.dumps({
                    "type": "response.output_audio_transcript.done", "response_id": "resp_1",
                    "transcript": "This is a mock realtime reply."}))
                in_audio_tokens = max(1, int(appended / 48000 * 10))
                await ws.send_text(json.dumps({"type": "response.done", "response": {
                    "id": "resp_1", "status": "completed", "usage": {
                        "total_tokens": in_audio_tokens + 42 + 12 + 8,
                        "input_tokens": in_audio_tokens + 42, "output_tokens": 12 + 8,
                        "input_token_details": {
                            "text_tokens": 42, "audio_tokens": in_audio_tokens,
                            "image_tokens": 0, "cached_tokens": 10,
                            "cached_tokens_details": {"text_tokens": 10, "audio_tokens": 0}},
                        "output_token_details": {"text_tokens": 8, "audio_tokens": 12}}}}))
    except Exception:  # noqa: BLE001 - client left
        return


@app.websocket("/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent")
async def gemini_live(ws: WebSocket):
    key = ws.headers.get("x-goog-api-key", "")
    await ws.accept()
    if not record("gemini_live", key, HOUSE_GEMINI, key_in_url="key=" in str(ws.url)):
        await ws.close(code=1008, reason="API key not valid")
        return
    try:
        first = await ws.receive()
        setup = json.loads(first.get("text") or first.get("bytes"))
        seen[-1]["setup_model"] = setup["setup"]["model"]
        await ws.send_bytes(json.dumps({"setupComplete": {}}).encode())
        audio_in = 0
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            payload = json.loads(message.get("text") or message.get("bytes"))
            # google-genai sends snake_case top-level keys; the docs show camelCase
            realtime = payload.get("realtimeInput") or payload.get("realtime_input") or {}
            if realtime.get("audio"):
                audio_in += len(base64.b64decode(realtime["audio"]["data"]))
            if (realtime.get("audioStreamEnd") or realtime.get("audio_stream_end")
                    or payload.get("clientContent") or payload.get("client_content")):
                reply = tone(0.5, 24000, 600)
                for i in range(0, len(reply), 9600):
                    await ws.send_bytes(json.dumps({"serverContent": {"modelTurn": {"parts": [{
                        "inlineData": {"mimeType": "audio/pcm;rate=24000",
                                       "data": base64.b64encode(reply[i:i + 9600]).decode()}}]}}
                    }).encode())
                prompt_audio = max(1, int(audio_in / 32000 * 25))
                await ws.send_bytes(json.dumps({
                    "serverContent": {"turnComplete": True},
                    "usageMetadata": {
                        "promptTokenCount": prompt_audio + 6, "responseTokenCount": 13,
                        "totalTokenCount": prompt_audio + 19,
                        "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": prompt_audio},
                                                {"modality": "TEXT", "tokenCount": 6}],
                        "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 13}]},
                }).encode())
                # per-turn report, matching the gateway's per_message default
                # (real semantics unverified: docs/providers/gemini.md)
                audio_in = 0
    except Exception:  # noqa: BLE001 - client left
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    print(f"mock upstream on 127.0.0.1:{args.port}", file=sys.stderr)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
