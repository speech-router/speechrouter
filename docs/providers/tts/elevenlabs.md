# ElevenLabs TTS

## Status
- Public TTS API is live (https://elevenlabs.io/docs/api-reference/text-to-speech/stream). Regional hosts: api.us.elevenlabs.io, api.eu.residency.elevenlabs.io, api.in.residency.elevenlabs.io, api.sg.residency.elevenlabs.io.
- Deprecated models: `eleven_turbo_v2_5`, `eleven_turbo_v2` (replacements: flash). `eleven_multilingual_v1` legacy. No acquisition found.
- Query param `optimize_streaming_latency` is deprecated.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream` (https://elevenlabs.io/docs/api-reference/text-to-speech/stream)
- Auth: `xi-api-key: <key>`; `Content-Type: application/json`.
- Query: `output_format` (default `mp3_44100_128`), `enable_logging` (default true; false = zero retention, Enterprise only).
- Body: `text` (required), `model_id` (default `eleven_multilingual_v2`), `language_code` (ISO 639-1; not supported by multilingual_v2), `voice_settings` {`stability` 0.5, `similarity_boost` 0.75, `style` 0, `use_speaker_boost` true, `speed` 1}, `seed`, `previous_text`, `next_text`, `previous_request_ids`/`next_request_ids` (max 3), `pronunciation_dictionary_locators` (max 3), `apply_text_normalization` (`auto`|`on`|`off`), `apply_language_text_normalization`, `audio_effects`. No free-form style/instructions field (style is via `voice_settings.style`; v3 supports inline audio tags in text - UNVERIFIED on this page).
- Response: 200, raw audio bytes streamed chunked in the requested format (docs say "stream of strings"; not SSE/base64). 422 on validation error.
- Example body:
```json
{"text":"Hello there.","model_id":"eleven_flash_v2_5","language_code":"en","voice_settings":{"stability":0.5,"similarity_boost":0.75,"speed":1.0}}
```
URL: `.../v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb/stream?output_format=pcm_16000`

## Output formats
(`output_format` query enum)
- MP3: `mp3_22050_32`, `mp3_24000_48`, `mp3_44100_32`, `mp3_44100_64`, `mp3_44100_96`, `mp3_44100_128` (default), `mp3_44100_192` (Creator tier+).
- PCM (raw s16le, per ElevenLabs convention; endianness/width not stated on this page - UNVERIFIED): `pcm_8000`, `pcm_16000`, `pcm_22050`, `pcm_24000`, `pcm_32000`, `pcm_44100` (Pro tier+), `pcm_48000`.
- Telephony: `ulaw_8000`, `alaw_8000`.
- Opus: `opus_48000_32`, `opus_48000_64`, `opus_48000_96`, `opus_48000_128`, `opus_48000_192`.
- No WAV enum listed on the stream page (UNVERIFIED elsewhere).
- Stereo audio_effects rejected with 400 for ulaw/alaw/pcm.

## Models
(https://elevenlabs.io/docs/overview/models)
- `eleven_v4` - most expressive, 90+ langs, 10,000 char limit.
- `eleven_v4_turbo` - expressive real-time, ~100 ms.
- `eleven_v3` - expressive, 70+ langs, 5,000 char limit.
- `eleven_v3_conversational` - real-time conversational, ~280 ms.
- `eleven_multilingual_v2` - 29 langs, 10,000 char limit (API default).
- `eleven_flash_v2_5` - ultra-fast, 32 langs, ~75 ms, 40,000 char limit.
- `eleven_flash_v2` - ultra-fast, English only, ~75 ms, 30,000 char limit.
- DEPRECATED: `eleven_turbo_v2_5`, `eleven_turbo_v2`. Legacy: `eleven_multilingual_v1`.

## Voices
- Identified by opaque `voice_id` in the URL path.
- List: `GET https://api.elevenlabs.io/v2/voices` (params: `search`, `category`=premade|cloned|generated|professional, `page_size` max 100, `next_page_token`, `voice_ids`, ...) (https://elevenlabs.io/docs/api-reference/voices/search). Legacy `GET /v1/voices` also returned the list below.
- Premade ids (from `GET https://api.elevenlabs.io/v1/voices` fetched 2026-10-13; list may be truncated):
  - `CwhRBWXzGAHq8TQ4Fs17` Roger; `EXAVITQu4vr4xnSDxMaL` Sarah; `FGY2WhTYpPnrIDTdsKH5` Laura; `IKne3meq5aSn9XLyUdCD` Charlie; `JBFqnCBsd6RMkjVDRZzb` George; `N2lVS1w4EtoT3dr4eOWO` Callum; `SAz9YHcvj6GT2YYXdXww` River; `SOYHLrjzK2X1ezoPC6cr` Harry; `TX3LPaxmHKxFdv7VOQHJ` Liam; `Xb7hH8MSUJpSbSDYk0k2` Alice; `XrExE9yKIg1WjnnlVkGX` Matilda; `bIHbv24MWmeRgasZH58o` Will; `cgSgspJ2msm6clMCkdW9` Jessica; `cjVigY5qzO86Huf0OWal` Eric; `nPczCjzI2devNBz1zQrb` Brian.
- Default: `JBFqnCBsd6RMkjVDRZzb` (George; used in official quickstart https://elevenlabs.io/docs/eleven-api/quickstart).
- Custom/cloned voice ids are allowed (account's own voices; `use_pvc_as_ivc` option for professional clones). Account-library access to a given premade voice not verified.

## WebSocket / input streaming
- `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input` (https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input). Query: `model_id`, `output_format`, `language_code`, `inactivity_timeout` (default 20, max 180), `sync_alignment`, `auto_mode`.
- Protocol: first message `{"text":" ", voice_settings, generation_config, xi_api_key}`; then `{"text":"... "}` (optionally `flush:true`); finish with `{"text":""}`. Server sends `{"audio":"<base64>", alignment...}` and finally `{"isFinal":true}`.

## Usage reporting
- Not documented on the stream page; character-cost response header (commonly `x-character-count`) UNVERIFIED in official docs read. Treat billed chars = len(text) and verify.

## Pricing (list price, pay-as-you-go/API)
Source: https://elevenlabs.io/pricing/api - checked 2026-10-13
- Per 1K characters: `eleven_v4` $0.08; `eleven_v4_turbo` $0.04; `eleven_v3` $0.08; `eleven_v3_conversational` $0.04; `eleven_multilingual_v2` $0.08; Flash/Turbo (`eleven_flash_v2_5`, `eleven_flash_v2`) $0.04.
- Per-model mapping for flash_v2 vs v2_5 and the page's "Turbo" row: page groups them as "Flash / Turbo".
- Billing unit: characters of input text (1 char = 1 credit at these rates; plan credit mapping per model UNVERIFIED). Free tier 10,000 chars/month.
- Subscription plans exist (Starter $6, Creator $22, Pro $99, Scale $299, Business $990); the table above is the API rate card.

## Errors
(https://elevenlabs.io/docs/eleven-api/resources/errors)
- 200 OK; 4xx request problems; 429 rate/concurrency limit; 500 server; 503 service_unavailable. Types: 400 `validation_error`/`invalid_request`, 401 `authentication_error`, 402 `payment_required`, 403 `authorization_error`, 404 `not_found`, 409 `conflict`, 429 `rate_limit_error`, 500 `internal_error`.
- Body: `{"detail":{"type","code","message","status"(legacy),"request_id","param"}}`. 422 validation: `{"detail":[{"loc":[],"msg":"","type":""}]}`.
