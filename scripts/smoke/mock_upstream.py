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


# ------------------------------------------------------- phase-2 TTS vendors
#
# The gateway's SPEECHROUTER_TTS_BASE_URLS points each vendor at
# /vendor/<provider>; this route answers in that vendor's wire format and
# checks the vendor-specific auth header carries the HOUSE key.

PHASE2_AUTH = {
    "elevenlabs": ("xi-api-key", "{k}"), "cartesia": ("authorization", "Bearer {k}"),
    "deepgram": ("authorization", "Token {k}"), "azure": ("ocp-apim-subscription-key", "{k}"),
    "google": ("x-goog-api-key", "{k}"), "rime": ("authorization", "Bearer {k}"),
    "inworld": ("authorization", "Basic {k}"), "fishaudio": ("authorization", "Bearer {k}"),
    "minimax": ("authorization", "Bearer {k}"), "groq": ("authorization", "Bearer {k}"),
    "murf": ("api-key", "{k}"), "speechmatics": ("authorization", "Bearer {k}"),
    # phase 3
    "xai": ("authorization", "Bearer {k}"), "mistral": ("authorization", "Bearer {k}"),
    "smallest": ("authorization", "Bearer {k}"), "together": ("authorization", "Bearer {k}"),
    # SigV4: the access key id rides the Credential scope (prefix match below)
    "aws": ("authorization", "AWS4-HMAC-SHA256 Credential={k}/"),
}


def _f32(pcm: bytes) -> bytes:
    samples = array.array("h")
    samples.frombytes(pcm)
    return array.array("f", (x / 32767 for x in samples)).tobytes()


@app.post("/vendor/{provider}/{rest:path}")
async def vendor_tts(provider: str, rest: str, request: Request):
    header, template = PHASE2_AUTH[provider]
    expected = template.format(k=f"mock-house-{provider}")
    raw = await request.body()
    presented = request.headers.get(header, "")
    if provider == "aws" and presented.startswith(expected):
        presented = expected  # signature itself is verified by unit tests
    if not record(f"{provider}_tts", presented, expected, path="/" + rest):
        return JSONResponse({"error": "bad key"}, status_code=401)
    text = "x" * 40
    if raw.startswith(b"{"):
        body = json.loads(raw)
        text = body.get("text") or body.get("transcript") or body.get("input") or text
    if provider == "aws":
        text = (json.loads(raw).get("Text") or text) if raw.startswith(b"{") else text
    rate = 16000 if provider in ("speechmatics", "aws") else 24000
    pcm = tone(0.2 + len(text) * 0.02, rate, 380)
    if provider == "google":
        return JSONResponse({"audioContent": base64.b64encode(wav_header(len(pcm)) + pcm)
                             .decode()})
    if provider in ("groq", "together"):
        return Response(wav_header(len(pcm)) + pcm, media_type="audio/wav")
    if provider == "mistral":
        f32 = _f32(pcm)

        async def mistral_sse():
            for i in range(0, len(f32), 19200):
                event = {"type": "speech.audio.delta",
                         "audio_data": base64.b64encode(f32[i:i + 19200]).decode()}
                yield f"data: {json.dumps(event)}\n\n"
            yield 'data: {"type": "speech.audio.done"}\n\n'
        return StreamingResponse(mistral_sse(), media_type="text/event-stream")
    if provider == "inworld":
        lines = [json.dumps({"result": {"audioContent": base64.b64encode(pcm[i:i + 9600])
                                        .decode(), **({"usage": {"processedCharactersCount":
                                                                 len(text)}} if i == 0 else {})}})
                 for i in range(0, len(pcm), 9600)]
        return Response("\n".join(lines), media_type="application/x-ndjson")
    if provider == "minimax":
        async def sse():
            for i in range(0, len(pcm), 9600):
                event = {"data": {"audio": pcm[i:i + 9600].hex(), "status": 1},
                         "base_resp": {"status_code": 0}}
                yield f"data: {json.dumps(event)}\n\n"
            final = {"data": {"audio": pcm.hex(), "status": 2},
                     "extra_info": {"usage_characters": len(text)},
                     "base_resp": {"status_code": 0, "status_msg": "success"}}
            yield f"data: {json.dumps(final)}\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream")
    headers = {"dg-char-count": str(len(text))} if provider == "deepgram" else {}
    if provider == "aws":
        headers = {"x-amzn-RequestCharacters": str(len(text))}

    async def chunks():
        for i in range(0, len(pcm), 4800):
            yield pcm[i:i + 4800]
            await asyncio.sleep(0.005)
    return StreamingResponse(chunks(), media_type="application/octet-stream", headers=headers)


@app.websocket("/vendor/xai/v1/tts")
async def xai_tts_socket(ws: WebSocket):
    """xAI native TTS socket: text.delta/done/clear -> audio.delta/done/clear."""
    ok = record("xai_tts_ws", ws.headers.get("authorization", ""), "Bearer mock-house-xai",
                query=str(ws.url.query))
    await ws.accept()
    if not ok:
        await ws.close(code=1008)
        return
    rate = int(ws.query_params.get("sample_rate", "24000"))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg["type"] == "text.delta":
                pcm = tone(len(msg["delta"]) * 0.02, rate, 300)
                await ws.send_text(json.dumps({"type": "audio.delta",
                                               "delta": base64.b64encode(pcm).decode()}))
            elif msg["type"] == "text.clear":
                await ws.send_text(json.dumps({"type": "audio.clear"}))
            elif msg["type"] == "text.done":
                await ws.send_text(json.dumps({"type": "audio.done", "trace_id": "mock"}))
    except Exception:  # noqa: BLE001 - client left
        return


@app.websocket("/vendor/deepgram/v2/speak")
async def flux_tts_socket(ws: WebSocket):
    """Deepgram Flux native socket: Speak/Flush/Interrupt/Close, binary audio."""
    ok = record("deepgram_flux_ws", ws.headers.get("authorization", ""),
                "Token mock-house-deepgram", query=str(ws.url.query))
    await ws.accept()
    if not ok:
        await ws.close(code=1008)
        return
    rate = int(ws.query_params.get("sample_rate", "24000"))
    spoken: list[str] = []
    billed = 0
    try:
        await ws.send_text(json.dumps({"type": "Connected", "request_id": "mock"}))
        while True:
            msg = json.loads(await ws.receive_text())
            if msg["type"] == "Speak":
                spoken.append(msg["text"])
                billed += len(msg["text"])
                await ws.send_bytes(tone(len(msg["text"]) * 0.02, rate, 340))
            elif msg["type"] == "Interrupt":
                text = "".join(spoken)
                await ws.send_text(json.dumps({
                    "type": "SpeechInterrupted", "audio_played_ms":
                        msg.get("playback_offset", {}).get("value", 0),
                    "text_spoken": text[: len(text) // 2],
                    "text_remaining": text[len(text) // 2:]}))
                spoken = []
            elif msg["type"] == "Close":
                await ws.send_text(json.dumps({"type": "SessionMetadata",
                                               "total_billable_character_count": billed}))
                await ws.close()
                return
    except Exception:  # noqa: BLE001 - client left
        return


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
