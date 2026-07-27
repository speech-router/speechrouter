# OpenAI — protocol brief (verified 2026-07-27)

Docs moved: platform.openai.com/docs → **developers.openai.com/api/docs**

## Realtime transcription (WS)
- `wss://api.openai.com/v1/realtime` — transcription sessions via `?intent=transcription` / session `"type":"transcription"` in `session.update` (GA mechanism)
- Server auth: `Authorization: Bearer`; browser auth via WS subprotocols `"realtime", "openai-insecure-api-key.<ephemeral>"` (mint at `POST /v1/realtime/client_secrets`)
- GA session shape (NESTED, not old flat `input_audio_format`):
```json
{"type":"session.update","session":{"type":"transcription","audio":{"input":{
  "format":{"type":"audio/pcm","rate":24000},
  "transcription":{"model":"gpt-realtime-whisper","language":"en"}}}}}
```
- Formats: `audio/pcm` (16-bit mono **24kHz**), `audio/pcmu`, `audio/pcma`
- Models: **`gpt-realtime-whisper`** (2026, natively streaming, $0.017/min, omit turn_detection, latency knob `delay`: minimal..xhigh); `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `whisper-1` (need VAD/commit chunking). `gpt-4o-transcribe-diarize` = **batch only**.
- turn_detection: `server_vad` {threshold, prefix_padding_ms, silence_duration_ms} or `semantic_vad` {eagerness}
- **AUDIO IS BASE64 IN JSON**: `{"type":"input_audio_buffer.append","audio":"<b64>"}`; manual `input_audio_buffer.commit` when VAD off
- Server events: `conversation.item.input_audio_transcription.delta` {item_id, delta}, `...completed` {item_id, transcript, usage}; VAD: `input_audio_buffer.speech_started` {audio_start_ms}, `.speech_stopped` {audio_end_ms}, `.committed`. Order by item_id — deltas across items can interleave.
- **NO word timestamps, NO diarization in realtime.** Capability matrix: word_timestamps=false for openai realtime models.
- WebRTC exists (`POST /v1/realtime/calls`, data channel "oai-events") — not for our proxy; WS is the transport.

## Batch POST /v1/audio/transcriptions
- 25 MB limit; formats flac mp3 mp4 mpeg mpga m4a ogg wav webm
- Params: file, model, language, prompt, response_format, temperature, `timestamp_granularities[]` (word|segment, **verbose_json only → whisper-1 only**), `stream` (SSE; ignored for whisper-1), `chunking_strategy` (required for diarize >30s), `include[]` (logprobs), `known_speaker_names[]`+`known_speaker_references[]` (diarize enrollment, ≤4 speakers)
- Format matrix: whisper-1 → json/text/srt/verbose_json/vtt; gpt-4o-(mini)-transcribe → json/text only; gpt-4o-transcribe-diarize → json/text/**diarized_json**
- verbose_json: {task, language, duration, text, segments[{id,seek,start,end,text,...}], words[{word,start,end}], usage{type:"duration",seconds}}
- diarized_json: segments[{id,start,end,**speaker**,text,type}]
- SSE stream events: `transcript.text.delta` → `transcript.text.done` (+ `transcript.text.segment` for diarize)
- Pricing: gpt-4o-transcribe ≈$0.006/min, mini ≈$0.003/min, gpt-realtime-whisper $0.017/min; whisper-1/diarize prices unverified — confirm before catalog entry.
