# Cartesia TTS

## Status
- Public TTS API live (https://docs.cartesia.ai/api-reference/tts/bytes). Current family: Sonic 3.6 (snapshot `sonic-3.6-2026-08-27`).
- Sunsetting 2026-10-20: all `sonic-2` and `sonic-turbo` snapshots and `sonic-3-2025-10-27` (https://docs.cartesia.ai/build-with-cartesia/tts-models/older-models). No acquisition found.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.cartesia.ai/tts/bytes`
- Headers: `Authorization: Bearer sk_car_...` (or short-lived access token JWT); `Cartesia-Version: 2026-08-14` (required; docs say only this value accepted/default); `Content-Type: application/json`.
- Body: `model_id`, `transcript`, `voice` (required; `{"id": "<voice id>"}` or string id; embeddings not accepted), `output_format` (object, required), `language` or `locale` (not both -> 400), `accent`, `normalization` (`auto` default | `off` | locale code), `pronunciation_dict_id`, `generation_config` {`volume` 0.5-2.0, `speed` 0.6-1.5, `emotion` e.g. `neutral`,`calm`,`angry`,`content`,`sad`,`scared`,`happy`,`excited`,... ~50 values}. generation_config supported on sonic-3 and newer. No free-text instructions field.
- Response: 200, raw audio bytes (binary, `audio/*`), chunked streaming; not SSE/base64 (SSE is a separate endpoint, not read).
- Example body:
```json
{"model_id":"sonic-3.6","transcript":"Hi there, it's awesome to meet you.","voice":{"id":"db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"},"language":"en","output_format":{"container":"raw","encoding":"pcm_s16le","sample_rate":24000},"generation_config":{"speed":1}}
```

## Output formats
- `output_format.container`: `raw` (requires `encoding` + `sample_rate`), `wav` (`encoding` default `pcm_s16le`, `sample_rate` default 44100), `mp3` (`sample_rate`, `bit_rate` in 32000|64000|96000|128000 (default)|192000).
- `encoding` enum: `pcm_f32le`, `pcm_s16le`, `pcm_mulaw`, `pcm_alaw`.
- `sample_rate` for all: 8000, 16000, 22050, 24000, 44100, 48000.
- Raw PCM s16le: `{"container":"raw","encoding":"pcm_s16le","sample_rate":<any above>}`. mulaw/alaw 8k: `{"container":"raw","encoding":"pcm_mulaw","sample_rate":8000}`.
- Opus: not offered (UNVERIFIED beyond the enums listed).

## Models
(https://docs.cartesia.ai/build-with-cartesia/tts-models/latest, .../older-models, bytes API enum)
- `sonic-3.6` - latest stable alias (default in bytes API).
- `sonic-3.6-YYYY-MM-DD` - pinned snapshot, e.g. `sonic-3.6-2026-08-27`.
- `sonic-3.5` (snapshot `sonic-3.5-2026-05-04` active) and `sonic-3` (snapshot `sonic-3-2026-01-12` active) - older, still active.
- `sonic-preview` - beta, not for production.
- DEPRECATED/sunset: `sonic-2`, `sonic-turbo`, `sonic` families (stop working 2026-10-20); `sonic-latest` and `sonic-3-latest` are deprecated aliases -> `sonic-preview` (though the bytes API enum still lists `sonic-latest`); `sonic-3-preview` -> `sonic-3`.
- Languages for 3.6: 44 (en, fr, de, es, pt, zh, ja, hi, it, ko, nl, pl, ru, sv, tr, ... ur).

## Voices
- Identified by UUID voice id.
- List: `GET https://api.cartesia.ai/voices` (same headers; params `limit` 1-100, `starting_after`, `q`, `gender`, `language`, `is_owner`, `expand[]=preview_file_url`; response `{data, has_more, next_page}`) (https://docs.cartesia.ai/api-reference/voices/list).
- Only one id verified in official docs: `db6b0ed5-d5d3-463d-ae85-518a07d3c2b4` (Skylar, public American English female). Other popular ids: UNVERIFIED (not fetched; use the list endpoint).
- Default: `db6b0ed5-d5d3-463d-ae85-518a07d3c2b4`.
- Custom/cloned voices allowed via their UUID (own org voices; `is_owner` filter).

## WebSocket / input streaming
- `wss://api.cartesia.ai/tts/websocket?cartesia_version=2026-08-14` auth `X-API-Key` header or `access_token` query (https://docs.cartesia.ai/api-reference/tts/websocket).
- Client sends `{model_id, transcript, voice, output_format, context_id, continue:true|false, flush, max_buffer_delay_ms}` per chunk; `{context_id, cancel:true}` to cancel. Server sends `chunk` (base64 audio), `flush_done`, `timestamps`, `done`, `error`.

## Usage reporting
- No usage/billing headers documented in the API conventions page (https://docs.cartesia.ai/use-the-api/api-conventions); usage is via admin-key usage endpoints. Per-request billed credits: UNVERIFIED.

## Pricing (list price, pay-as-you-go/API)
Source: https://cartesia.ai/pricing - checked 2026-10-13
- Billing unit: credits; 1 credit = 1 character (~750-800 credits per minute of audio). Break tags count 1 credit. Pro voice clone speech 1 credit/char. Model-specific pricing: UNVERIFIED (page shows no per-model split).
- Plans: Free $0 (20K credits), Pro $5 (100K), Startup $49 (1.25M), Scale $299 (8M), Enterprise custom.
- Overage (if enabled): Pro $65/1M credits ($0.000065/char), Startup $45/1M, Scale $38/1M. Cheapest self-serve plan with API access: Pro (UNVERIFIED that Free lacks API access) -> overage $65 per 1M characters. Blocked at limit if overages off.

## Errors
(https://docs.cartesia.ai/use-the-api/api-conventions)
- Standard HTTP codes; specific list not given. `Cartesia-Version` >= 2026-03-01: JSON `{"error_code"(nullable),"title","message","request_id","doc_url"(optional)}`. WS/SSE errors add `type`, `done`, `status_code`, `context_id`. Legacy versions: plain text `Title: Message`.
