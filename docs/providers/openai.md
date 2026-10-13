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

## TTS (added 2026-10-13, SR-TTS-LIVE) — documented, NOT yet live-verified

- `POST /v1/audio/speech` `{model, input, voice, response_format, speed?, instructions?, stream_format?}`.
  Formats mp3 / opus (ogg) / aac / flac / wav / pcm (s16le mono 24 kHz, no header).
- `stream_format: "sse"` (gpt-4o-mini-tts only; tts-1* reject it) → `speech.audio.delta {audio: b64}` …
  `speech.audio.done {usage: {input_tokens, output_tokens, total_tokens}}`. **The only place token usage
  appears**, so the adapter always uses SSE for token-priced models and decodes to raw bytes.
- input_tokens = text, output_tokens = audio. Estimated rate used only on cancellation: 1250 audio
  tokens/min (derived from OpenAI's published ~$0.015/min at $12/1M). **Probe:** `scripts/tts_live_probe.py --exp openai_tts`.
- Voices: gpt-4o-mini-tts 13 (alloy ash ballad coral echo fable nova onyx sage shimmer verse marin cedar);
  tts-1/-hd 9 (no ballad/verse/marin/cedar). Verify the list against a live key.
- `instructions` gpt-4o-mini-tts only; `speed` honoured by tts-1* (docs say ignored by gpt-4o-mini-tts).
- Pricing (2026-10-13): gpt-4o-mini-tts $0.60/1M text in + $12/1M audio out; tts-1 $15/1M chars; tts-1-hd $30/1M chars.

## Realtime live passthrough (added 2026-10-13) — documented, NOT yet live-verified

- `wss://api.openai.com/v1/realtime?model=<m>`, `Authorization: Bearer`. The gateway serves the same path
  under `/v1`, so OpenAI SDKs work with `base_url=<gateway>/v1` (SDK maps http→ws, https→wss).
- Browser auth: subprotocols `realtime`, `openai-insecure-api-key.<key>`; the gateway accepts its `st_`
  tokens there. Beta clients: `openai-beta.realtime-v1` subprotocol → forwarded as `OpenAI-Beta: realtime=v1`.
- Usage: `response.done.response.usage` per response — `input_token_details {text_tokens, audio_tokens,
  image_tokens, cached_tokens, cached_tokens_details{text_tokens, audio_tokens}}`, `output_token_details
  {text_tokens, audio_tokens}`. Cached is a SUBSET of input: the meter subtracts it into `cached_*` units.
- Audio: client `input_audio_buffer.append {audio}`, server `response.output_audio.delta {delta}` (GA) /
  `response.audio.delta` (beta). Format from `session.audio.{input,output}.format.type` (`audio/pcm` 24 kHz,
  `audio/pcmu`/`audio/pcma` 8 kHz) or beta `input_audio_format`.
- Input transcription (`session.audio.input.transcription.model`) is billed separately at the
  transcription model's rate: metered as an `stt_stream` companion event (PLAN §3.0).
- Fallback estimate when no usage arrives: 10 tok/s in, 20 tok/s out (commonly cited; unverified).
- Model is fixed per connection; `session.update` with another `model` is refused by the gateway.
- Pricing (per 1M, 2026-10-13): gpt-realtime-2.1 audio 32/0.40 cached/64 out, text 4/0.40/24, image 5;
  -2.1-mini audio 10/0.30/20, text 0.60/0.06/2.40, image 0.80.
