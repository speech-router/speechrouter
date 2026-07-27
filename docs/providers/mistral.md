# Mistral (Voxtral) — protocol brief (verified 2026-07-27)

Feb 2026 refresh: "Voxtral Transcribe 2".

## Batch POST https://api.mistral.ai/v1/audio/transcriptions
- OpenAI-style multipart + extras: `file` OR **`file_url`** (remote URL!), `language`, `timestamp_granularities` (segment and/or word), **`diarize: true`**, **`context_bias`** (≤100 terms, English-optimized) — keyword boosting
- Model: `voxtral-mini-latest` → Voxtral Mini Transcribe V2. (voxtral-small = chat audio-in, NOT this endpoint)
- **Up to 3 HOURS of audio per request** (vs 25MB elsewhere). 13 languages. ~4% WER FLEURS claim.
- $0.003/min ($0.18/hr)
- Exact response JSON schema unverified — pull a live sample before finalizing adapter normalization.

## Realtime WS (protocol verified from SDK source 2026-07-27, commit b0613c7)
- `wss://api.mistral.ai/v1/audio/transcriptions/realtime?model=voxtral-mini-transcribe-realtime-2602` — model is the ONLY query param
- Auth: `Authorization: Bearer` header on upgrade. No subprotocol.
- **Server sends first**: `{"type":"session.created","session":{request_id, model, audio_format, target_streaming_delay_ms}}` — wait for it before anything.
- Optional BEFORE audio: `{"type":"session.update","session":{"audio_format":{"encoding":"pcm_s16le","sample_rate":16000},"target_streaming_delay_ms":800}}` → `session.updated`. Encodings: pcm_s16le/s32le/f16le/f32le/mulaw/alaw.
- Audio: **base64 in JSON text frames** `{"type":"input_audio.append","audio":"<b64>"}`, **max 262144 decoded bytes/message**. Never binary frames.
- End sequence: `{"type":"input_audio.flush"}` → `{"type":"input_audio.end"}` → read until `transcription.done` → close 1000.
- Server events: `transcription.language` {audio_language}; `transcription.text.delta` {text} (incremental); `transcription.segment` {text, start, end, speaker_id?} (finalized span, SECONDS); `transcription.done` {text, language, segments[] (type "transcription_segment" w/ underscore!), usage{prompt_audio_seconds}}; `error` {error:{message (str|obj), code (int)}}.
- Keepalive: none app-level — standard WS ping/pong (websockets defaults) suffices.
- No diarization/word timestamps realtime. $0.006/min. Open weights Voxtral-Mini-4B-Realtime-2602 (Apache-2.0) = self-host fallback.
