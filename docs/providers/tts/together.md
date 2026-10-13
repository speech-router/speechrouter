# Together AI TTS (Kokoro)

## Status
- Live. Docs host is `api.together.ai`; `api.together.xyz` is not in the official TTS docs (UNVERIFIED whether it still works). https://docs.together.ai/docs/text-to-speech

## HTTP endpoint
- `POST https://api.together.ai/v1/audio/speech`, `Authorization: Bearer $TOGETHER_API_KEY`, JSON.
- Body: `model` (req; `hexgrad/Kokoro-82M`), `input` (req), `voice` (req), `response_format` (`mp3|wav|raw`, default `wav`; docs text also mentions `mulaw`; with `stream:true` only `raw`), `response_encoding` (`pcm_f32le` default | `pcm_s16le` | `pcm_mulaw` | `pcm_alaw`; only for `raw`), `sample_rate` (int, default 44100; Kokoro and Orpheus always output 24000), `bit_rate` (mp3 only; 32000..192000), `language` (default `en`), `stream` (bool, default false), `alignment`/`segment` (per docs page), `extra_params` {`pronunciation_dict`}. https://docs.together.ai/reference/audio-speech
- Non-stream response: binary (`audio/wav`, `audio/mpeg`, or `application/octet-stream`).
- Stream response (`stream:true`, `response_format:"raw"`): SSE; chunk line `data: {"type":"conversation.item.audio_output.delta","item_id":"...","delta":"<base64>"}` and final `data: [DONE]`. (Alignment only: `conversation.item.word_timestamps` with `words`,`start_seconds`,`end_seconds`.) https://docs.together.ai/docs/inference/text-to-speech/streaming
- Conflict: the OpenAPI summary describes SSE chunk as `{"object":"audio.tts.chunk","model":...,"b64":"..."}`; the streaming guide shows the `conversation.item.audio_output.delta` shape. Which is live: UNVERIFIED; parse both.
```
curl -X POST https://api.together.ai/v1/audio/speech -H "Authorization: Bearer $TOGETHER_API_KEY" -H "Content-Type: application/json" -d '{"model":"hexgrad/Kokoro-82M","input":"Hello","voice":"af_heart","response_format":"raw","response_encoding":"pcm_s16le","stream":true}'
```

## WebSocket
- `wss://api.together.ai/v1/audio/speech/websocket?model=hexgrad/Kokoro-82M&voice=af_heart[&max_partial_length=250&language=en]`, Bearer header. https://docs.together.ai/reference/audio-speech-websocket
- Client: `input_text_buffer.append` {text}, `input_text_buffer.commit`, `input_text_buffer.clear`, `tts_session.updated` {session:{voice,...}}, optional `context_id` (default "default").
- Cancel: `{"type":"context.cancel","context_id":"..."}` -> server `context.cancelled`. Server: `session.created`, `conversation.item.audio_output.delta` (base64 PCM s16le mono 24000 Hz), `...audio_output.done`, `conversation.item.tts.failed`.

## Models
- `hexgrad/Kokoro-82M` (confirmed id). Also `canopylabs/orpheus-3b-0.1-ft`, Cartesia, Minimax, Rime, Qwen3 TTS (not scoped here).

## Voices
- Kokoro ~50 voices; docs name `af_heart`, `af_bella`, `am_adam`, `bf_emma`, `bm_george`, `zf_xiaoxiao`; also `af_alloy` (WS example). Full list: `GET https://api.together.ai/v1/voices?model=hexgrad/Kokoro-82M`. Mixing: `af_bella(2)+af_heart(1)`. Remaining ids to reach 20: UNVERIFIED. Default voice: none on HTTP (required); WS default voice `tara` is an Orpheus voice (Kokoro default UNVERIFIED).

## Formats & rates
- Kokoro native 24000 Hz. `raw` + `pcm_mulaw` gives mu-law, but `sample_rate` 8000 for Kokoro is not honored per docs (Kokoro always 24000), so true 8 kHz mu-law is NOT native; resample client-side. (Qwen accepts 8000, not Kokoro.)

## Usage reporting
- None documented. UNVERIFIED.

## Pricing https://www.together.ai/pricing , checked 2026-10-13
- Kokoro-82M TTS $4.00 per 1M characters (also: Orpheus $15, Cartesia Sonic-2/-3 $65). Unit: input characters.

## Limits
- No input or rate limits documented on TTS pages (UNVERIFIED). WS `max_partial_length` 250.

## Errors
- WS: `invalid_api_key` 401, `missing_api_key` 401, `model_not_available` 400, invalid text 400; error object fields `message,type,param,code`. HTTP 400/429 return `{"error":{"type","message",...}}`.
