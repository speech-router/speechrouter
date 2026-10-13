# Inworld TTS

## Status
- Live. Current models are `inworld-tts-2` and `inworld-tts-2-flash` (https://docs.inworld.ai/tts/tts-models).
- Deprecated: `inworld-tts-1` and `inworld-tts-1-max` were discontinued 2026-06-15 and are routed to newer models. `inworld-tts-1.5-max` and `inworld-tts-1.5-mini` are deprecated and not recommended.
- No acquisition. Checked 2026-10-13.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.inworld.ai/tts/v1/voice:stream` (https://docs.inworld.ai/api-reference/ttsAPI/texttospeech/synthesize-speech-stream).
- Non-streaming: `POST https://api.inworld.ai/tts/v1/voice` returns one JSON object `{audioContent, usage}`. Max text 2,000 UTF-16 code units (https://docs.inworld.ai/api-reference/ttsAPI/texttospeech/synthesize-speech).
- Auth: `Authorization: Basic <INWORLD_API_KEY>`. Use the Portal's Base64 credential string as-is, without re-encoding. `Content-Type: application/json`. No extra ids.
- Body fields:
  - `text`: up to 4,000 UTF-16 code units on the streaming endpoint.
  - `voiceId`: or `voiceDesign` (preview), not both.
  - `modelId`: set explicitly.
  - `audioConfig.audioEncoding`: default `MP3`.
  - `audioConfig.sampleRateHertz`: 8000-48000.
  - `audioConfig.bitRate`: MP3 and OGG_OPUS only, default 128000.
  - `audioConfig.speakingRate`: 0.5-1.5, default 1.0.
  - `language`: BCP-47 tag, e.g. `en-US`.
  - `deliveryMode`: `STABLE`, `BALANCED` or `CREATIVE`. `inworld-tts-2` only.
  - `instruction`: English style instruction. `inworld-tts-2` only.
  - `temperature`: ignored on `inworld-tts-2`.
  - Other optional fields: `timestampType` (`WORD` or `CHARACTER`), `timestampTransportStrategy` (`SYNC` or `ASYNC`), `lipsyncConfig`, `applyTextNormalization`, `enhanceGeneration`, `synthesisContext`.
- Response: NDJSON (not SSE), one JSON object per line.
  - Each line looks like `{"result":{"audioContent":"<base64>","usage":{...},"timestampInfo":{...}}}`.
  - Buffer to newline, parse each line, and base64-decode each chunk separately. Do not concatenate base64 strings before decoding.
  - Timestamp-only lines can arrive after audio, so read to EOF.
  - A stream can return HTTP 200 and then end with `{"error":{"code":3,"message":"..."}}`.
- Example body:
```json
{"text":"Hello from the gateway.","voiceId":"Ashley","modelId":"inworld-tts-2",
 "audioConfig":{"audioEncoding":"PCM","sampleRateHertz":24000},"language":"en-US"}
```

## Output formats
- `audioConfig.audioEncoding` enum: `LINEAR16`, `MP3` (default), `OGG_OPUS`, `ALAW`, `MULAW`, `FLAC`, `PCM`, `WAV`.
- `PCM`: raw s16le with no header. Use this for raw PCM.
- `LINEAR16`: a full WAV header in EVERY streamed chunk. Do not feed it to a raw PCM player.
- `WAV`: header in the first chunk only.
- `sampleRateHertz` accepts 8000-48000. The default is 8000 for `MULAW` and `ALAW`, and 48000 otherwise, capped at the model's native rate.
- Native per-model sample rate: UNVERIFIED. The docs don't state it.

## Models
- `inworld-tts-2`: flagship Realtime TTS-2. Best quality, steering via `deliveryMode` and `instruction`, 200+ languages and locales, TTFB ~100 ms.
- `inworld-tts-2-flash`: fastest and cheapest, TTFB ~20 ms, 200+ languages and locales.
- Deprecated: `inworld-tts-1`, `inworld-tts-1-max` (discontinued), `inworld-tts-1.5-max`, `inworld-tts-1.5-mini`.

## Voices
- Voices are identified by `voiceId`. System voice ids equal the display name. Workspace clones are prefixed with the workspace id, e.g. `<workspace>__my_clone_...`.
- List: `GET https://api.inworld.ai/voices/v1/voices`, with `filter` (e.g. `source = "SYSTEM" AND lang_code = "en"`), `pageSize` (max 2000) and `pageToken`. The same `Authorization: Basic` header applies (https://docs.inworld.ai/api-reference/voiceAPI/voiceservice/list-voices).
- A TTS-scoped list `GET https://api.inworld.ai/tts/v1/voices?filter=language=en` also exists (https://docs.inworld.ai/api-reference/ttsAPI/texttospeech/list-voices).
- Verified premade ids (docs examples):
  - `Ashley`: warm natural female. Default, also the Pipecat default.
  - `Alex`: energetic expressive male.
  - `Dennis`: middle-aged, smooth, calm male. Default in the Inworld voice-agent template.
- A larger catalog (419 voices on 2026-07-07, per an Inworld guide) exists. Other ids are UNVERIFIED, so list them via the API.
- Arbitrary ids are not allowed. The id must exist in List voices, and an unknown voice returns 4XX `code 5` "Unknown voice: X not found!". Workspace clones are allowed.

## WebSocket / input streaming
- `wss://api.inworld.ai/tts/v1/voice:streamBidirectional` (https://docs.inworld.ai/api-reference/ttsAPI/texttospeech/synthesize-speech-websocket). The auth page text was not shown, so assume the same Basic key. UNVERIFIED.
- Client messages: `create` (requires `voiceId` and `modelId`, optional `audioConfig` and `autoMode`, optional `contextId`), `send_text` (max 2000 UTF-16 units per message, optional `flush_context`), `flush_context`, `close_context`. Multiple independent contexts share one socket.
- Server messages: context created, audio chunk (`audioContent` base64 plus `usage.processedCharactersCount`), flush completed, context closed. All carry `result.contextId` and a `status`.

## Usage reporting
- Yes. `usage.processedCharactersCount` (UTF-16 code units) is reported on the first streamed message, and later messages report 0, so sum them or keep the first.
- The non-streaming response includes `usage.processedCharactersCount` and `usage.modelId`.
- The full submitted text is metered when the first response is emitted. Cancelling does not reduce billing.

## Pricing (list price, pay-as-you-go/API)
- Source: https://inworld.ai/pricing, checked 2026-10-13.
- Unit: per 1M characters. The page assumes ~1,000 characters per minute of audio. The metering field counts UTF-16 code units.
- On-Demand (free to start, pay-as-you-go): `inworld-tts-2` is $25 per 1M chars, and `inworld-tts-2-flash` is $15 per 1M chars.
- Plan tiers, TTS-2 / TTS-2 Flash per 1M chars: Creator $25/mo $20/$10, Builder $100/mo $17.50/$9, Developer $300/mo $15/$8, Growth $1,500/mo $12.50/$7, Enterprise as low as $5 / sub-$5.
- Overage is charged at the plan rate.
- Pricing for the deprecated 1.x models: UNVERIFIED.

## Errors
- Non-streaming 4XX body: `{code, message, details}`, e.g. `code: 5` "Unknown voice". Codes are gRPC status codes, not HTTP numbers.
- Streaming: check the HTTP status, and also check each NDJSON line for `{"error":{"code":3,"message":"..."}}`. The stream can fail after a 200.
- Invalid `language` or `visemeSet` returns an error (`INVALID_ARGUMENT`). Output over 16 MB can fail, so use streaming or a compressed format.
- A full error table was not published. Specific HTTP codes such as 401 or 429 are UNVERIFIED.
