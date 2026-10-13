# Murf TTS

## Status
- Live. Falcon 2 (`falcon-2`) is the streaming model. Gen2 is decommissioned for streaming; still available on the non-streaming `/v1/speech/generate`. https://murf.ai/api/docs/introduction/overview
- WebSocket endpoint serves Falcon only.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://global.api.murf.ai/v1/speech/stream` (also `https://api.murf.ai/v1/speech/stream`, which resolves to us-east; regional hosts `us-east|us-west|in|ca|kr|me|jp|au|eu-central|uk|sa-east.api.murf.ai`). https://murf.ai/api/docs/api-reference/text-to-speech/stream
- Auth: header `api-key: <KEY>` (Murf returns 403, not 401, on bad key). Docs also list an optional `token` header (generate-token endpoint).
- Body (JSON): `text` (req), `voiceId` (req; e.g. `Natalie`, `Gordon`, or `en-US-natalie`), `model` (`falcon-2`, default), `format` (default `WAV`), `sampleRate` (default 24000), `channelType` (`MONO` default / `STEREO`), `locale` (e.g. `en-US`), `style`, `rate` (-50..50), `pitch` (-50..50), `volumeOffset` (-50..50). Inline `[pause 1s]` supported.
- Response: raw audio bytes, chunked transfer encoding. https://murf.ai/api/docs/text-to-speech/streaming
```
curl -X POST https://global.api.murf.ai/v1/speech/stream -H "api-key: $MURF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hi, how are you?","voiceId":"Gordon","locale":"en-US","model":"falcon-2","format":"PCM","sampleRate":24000}' --output out.pcm
```

## Output formats
- `format` enum: `MP3`, `FLAC`, `WAV`, `ALAW`, `ULAW`, `OGG`, `PCM` (PCM = 16-bit mono per docs example; little-endian: UNVERIFIED).
- `sampleRate` enum (stream): 8000, 16000, 24000, 44100, 48000 (default 24000). Gen2 generate: 8000, 24000, 44100, 48000 (default 44100).
- WAV streamed has a 44-byte header with 0xFFFFFFFF sizes (WS docs); use `PCM` to avoid. No separate opus (OGG only).

## Models
- `falcon-2`: ultra-fast streaming, TTFA <100 ms, multilingual switching. Aliases `falcon`, `falcon2` on WS.
- `gen2` (request field `modelVersion`: `GEN2`): studio quality, 44.1 kHz native, non-streaming only. https://murf.ai/api/docs/text-to-speech-models/gen-2

## Voices
- `voiceId` string. List: `GET https://api.murf.ai/v1/speech/voices?model=falcon-2|gen2` (returns `voiceId`, `displayName`, `gender`, `locale`, `supportedLocales`).
- Falcon 2 ids are plain names: `Natalie`, `Ariana`, `Miles`, `Amara`, `Maverick`, `Charles`, `Alicia`, `Gordon`, `Ken` (examples seen in docs; full Falcon list via endpoint). Gen2 ids are locale-prefixed: `en-US-natalie`, `en-US-terrell`, `en-US-ariana`, `en-US-miles`, `en-US-zion`, `en-US-amara`, `en-US-maverick`, `en-US-paul`, `en-US-charles`, `en-US-ken`, `en-US-carter`, `en-US-phoebe`, `en-US-riley`, `en-US-naomi`, `en-US-alicia`. https://murf.ai/api/docs/voices-styles/voice-library
- Default: none (required). Custom: instant and professional cloning documented (plan availability UNVERIFIED).

## WebSocket / input streaming
- `wss://global.api.murf.ai/v1/speech/stream-input?api_key=...&model=falcon-2&sample_rate=24000&format=PCM`. https://murf.ai/api/docs/api-reference/text-to-speech/stream-input
- JSON messages `sendText` (`text`, `context_id`, `end`), voice config via `voice_config` (`voice_id`, `style`, `rate`, `pitch`, `volumeOffset`, `locale`). Server frames: base64 `audio`, `timestamps`, `final`, `warning`, `error`. Closes after 3 min idle.

## Usage reporting
- `/generate` returns `remainingCharacterCount` and `audioLengthInSeconds`. The `/stream` response has no usage body (raw bytes); UNVERIFIED for headers.

## Pricing (list price, pay-as-you-go/API)
- Unit: per 1,000 characters. Falcon 2: $0.01 per 1,000 chars ($10 per 1M). Gen2: $0.03 per 1,000 chars ($30 per 1M). Pay-as-you-go minimum purchase $10 (help center); new API users get $10 free credit (search snippet of murf.ai/pricing; UNVERIFIED on the page itself). Sources: https://help.murf.ai/murf-api-pay-as-you-go, https://murf.ai/api/docs/text-to-speech-models/falcon-2. Checked 2026-10-13. murf.ai/pricing could not be fetched directly.
- Concurrency: Falcon 5 (us-east) / 2 (other regions); Gen2 5. https://murf.ai/api/docs/resources/rate-limits

## Errors
- HTTP: 400, 402 (expired subscription or character limit exhausted), 403 (invalid key), 408, 429 (concurrency), 500, 503. https://murf.ai/api/docs/text-to-speech/errors
- HTTP error JSON body shape: not documented (UNVERIFIED). WS error frame: `{"error","error_code","fatal","context_id","trace_id"}`.
