# Fish Audio TTS

## Status
- Live. Current models are `s2.1-pro` (default), `s2.1-pro-free`, `s2-pro`, `drama-3` and `s1`.
- `s1` is deprecated and retires 2026-12-31. After that, requests naming `s1` are served and billed as `s2.1-pro`.
- Sources: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech and https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits. Checked 2026-10-13.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.fish.audio/v1/tts`. The response uses chunked transfer encoding, and the body is raw audio bytes in the requested format. It is not SSE and not base64.
- Auth: `Authorization: Bearer <api_key>`. The model is selected with a request header `model: s2.1-pro`, not a body field. No extra ids.
- Content types: `application/json` and `application/msgpack`. MessagePack is required only when sending inline `references` (raw reference audio bytes).
- Body fields:
  - `text`: required.
  - `reference_id`: a voice model id string, or an array for multi-speaker.
  - `references`: inline reference audio, msgpack only.
  - `format`: `wav`, `pcm`, `mp3` (default) or `opus`.
  - `sample_rate`: an integer, or null for the format default.
  - `mp3_bitrate`: 64, 128 (default) or 192.
  - `opus_bitrate`: -1000 (auto), 24000, 32000, 48000 or 64000.
  - `prosody`: `{speed (0.5-2.0, default 1), volume (dB, default 0), normalize_loudness (S2 family only)}`.
  - `latency`: `low`, `normal` (default) or `balanced`.
  - `chunk_length`: 100-300, default 300.
  - `min_chunk_length`: 0-100, default 50.
  - `normalize`: default true.
  - `temperature`: default 0.7.
  - `top_p`: default 0.7.
  - `repetition_penalty`: default 1.2.
  - `max_new_tokens`: default 1024.
  - `condition_on_previous_chunks`: default true.
  - `early_stop_threshold`: default 1.
  - `features`: e.g. `["quality-guard"]`.
  - `pronunciation_dictionary`: up to 3.
- No dedicated `language` field was found in the docs. Language is inferred from the text.
- Emotion and style are expressed inline in the text for S2 models. The exact tag syntax is UNVERIFIED. `<|speaker:0|>` tags are for multi-speaker (S2 family and `drama-3`, not `s1`).
- Example (https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech):
```
POST https://api.fish.audio/v1/tts
Authorization: Bearer <token>
Content-Type: application/json
model: s2.1-pro
{"text":"Hello! Welcome to Fish Audio.","reference_id":"9a9cf47702da476aa4629e2506d4a857","format":"pcm","sample_rate":24000,"latency":"low"}
```
- The `reference_id` above appears in Fish's own examples (https://docs.fish.audio/developer-guide/core-features/text-to-speech). `sample_rate: 24000` is allowed for WAV/PCM per the list below.

## Output formats
- `format` enum: `wav`, `pcm`, `mp3` (default), `opus`.
- WAV/PCM: 8000, 16000, 24000, 32000 or 44100 Hz, 16-bit mono. `pcm` is raw s16le (header-less, assumed from the name). The default is 44100.
- MP3: 32000 or 44100 Hz, mono.
- Opus: 48000 Hz, mono. The default sample rate is 48000.
- No mulaw or alaw. Resample and convert yourself. Native model rate is UNVERIFIED (the default is 44100).

## Models
- `s2.1-pro`: current default and recommended production model.
- `s2.1-pro-free`: the same model at $0, for the free developer tier. No TTFA or DPA guarantees.
- `s2-pro`: previous S2 generation.
- `drama-3`: multi-speaker and dialogue model. A description is UNVERIFIED beyond multi-speaker support. Its price is UNVERIFIED because the pricing page doesn't list it.
- `s1`: deprecated, retires 2026-12-31.
- Unrecognized `model` header values fall back to `s2.1-pro`.

## Voices
- Voices are "models" identified by `reference_id`, a 32-character hex `_id`.
- List: `GET https://api.fish.audio/model` (Bearer) with `page_size` (1-100), `page_number`, `title`, `tag`, `language`, `self`, `licensed` and `sort_by` (`score`, `task_count` or `created_at`). The response is `{total, items[{_id,title,description,languages,tags,visibility,state,...}]}` (https://docs.fish.audio/api-reference/endpoint/model/list-models).
- There is no fixed premade catalog in the docs. Use `sort_by=task_count` or `licensed=true` to find popular voices.
- Verified id from official examples: `9a9cf47702da476aa4629e2506d4a857` (its name is UNVERIFIED). Use it as a placeholder default only.
- Other popular voice ids and names are UNVERIFIED. They must be resolved via the Voice Library or the list API.
- Omitting `reference_id` falls back to an unspecified default voice (UNVERIFIED).
- Arbitrary ids are allowed. Any public model id, or one of your own, works. An unknown id returns an error (the exact code is UNVERIFIED).

## WebSocket / input streaming
- `wss://api.fish.audio/v1/tts/live` with `Authorization: Bearer` and optional `model` header (https://docs.fish.audio/api-reference/endpoint/websocket/tts-live).
- Client messages (MessagePack): `{event:"start", request:{...same fields as HTTP...}}`, then `{event:"text", text}`, `{event:"flush"}` and `{event:"stop"}`.
- Server messages: `{event:"audio", audio:<bytes>}` chunks, then `{event:"finish", reason:"stop"|"error"}`.

## Usage reporting
- None found. The docs show no usage, character or byte fields in the response, and no billing headers. Compute `len(text.encode("utf-8"))` yourself. Billing-header presence is UNVERIFIED.

## Pricing (list price, pay-as-you-go/API)
- Source: https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits, checked 2026-10-13.
- Billing UNIT: "measured in millions of UTF-8 bytes of input text". It is bytes, NOT characters. CJK characters are typically 3 bytes each, and ASCII is 1 byte.
- `s2.1-pro`: $15.00 per 1M UTF-8 bytes.
- `s2-pro`: $15.00 per 1M UTF-8 bytes.
- `s1`: $15.00 per 1M UTF-8 bytes. Deprecated.
- `s2.1-pro-free`: $0.00.
- `drama-3`: price UNVERIFIED.
- The singular `.../pricing-and-rate-limit` URL and https://fish.audio/pricing/ returned 404. Subscription plan tiers are UNVERIFIED.

## Errors
- Errors are JSON `{status, message, reason?}` (https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech).
- Documented HTTP codes: 401 (unauthorized), 402 (payment required), 503 (server overloaded). 422 validation is likely but UNVERIFIED. A WS error ends with `finish` and `reason:"error"`.
