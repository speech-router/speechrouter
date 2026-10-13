# Groq TTS

## Status
- Live. Orpheus models are current: `canopylabs/orpheus-v1-english` and `canopylabs/orpheus-arabic-saudi` (Arabic model marked "Preview" on its model page). https://console.groq.com/docs/text-to-speech
- DEPRECATED: `playai-tts` and `playai-tts-arabic`, shutdown 12/31/2025 (users emailed 2025-12-23). Replacements: `canopylabs/orpheus-v1-english`, `canopylabs/orpheus-arabic-saudi`. https://console.groq.com/docs/deprecations
- Do not use PlayAI ids; they are past shutdown as of 2026-10-13.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.groq.com/openai/v1/audio/speech` (OpenAI-compatible). https://console.groq.com/docs/api-reference#audio-speech
- Auth: `Authorization: Bearer $GROQ_API_KEY`, `Content-Type: application/json`.
- Body: `model` (req), `input` (req, text), `voice` (req), `response_format` (opt), `sample_rate` (opt int, default 48000), `speed` (opt, 0.5 to 5, default 1). No language/style fields; style is via inline vocal directions like `[cheerful]` (English model only).
- `input` limit: 200 characters per request (docs: https://console.groq.com/docs/text-to-speech/orpheus). Long text must be chunked client-side.
- Response: raw audio bytes of the requested container (not base64 JSON). Whether the body is chunk-streamed progressively: UNVERIFIED (docs show save-to-file only; no streaming section found).
- Doc inconsistency: API reference lists `response_format` enum `flac, mp3, mulaw, ogg, wav` (default `mp3`, though the Returns text says wav); the Orpheus page says "The only supported format is wav" and the quickstart defaults to `wav`. Treat only `wav` as confirmed; others UNVERIFIED in practice for Orpheus.
```
curl https://api.groq.com/openai/v1/audio/speech -X POST \
  -H "Authorization: Bearer $GROQ_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"canopylabs/orpheus-v1-english","input":"Hello [cheerful] there.","voice":"austin","response_format":"wav"}' \
  --output out.wav
```

## Output formats
- API reference `response_format` enum: `flac`, `mp3`, `mulaw`, `ogg`, `wav`. No `pcm`, no `opus`, no `alaw`. (Orpheus page says wav only; see above.)
- `sample_rate` enum: 8000, 16000, 22050, 24000, 32000, 44100, 48000 (default 48000).
- Raw PCM s16le: not offered; use `wav` and strip the 44-byte header (header assumption UNVERIFIED).
- Native rate of Orpheus: UNVERIFIED.

## Models
- `canopylabs/orpheus-v1-english`: expressive English TTS with vocal directions (`[cheerful]`, `[whisper]`).
- `canopylabs/orpheus-arabic-saudi`: Saudi-dialect Arabic, no vocal directions, Preview.

## Voices
- Identified by lowercase name string in `voice`. No list endpoint found (UNVERIFIED); voices are documented on https://console.groq.com/docs/text-to-speech/orpheus.
- English: `autumn`, `diana`, `hannah` (female); `austin`, `daniel`, `troy` (male).
- Arabic: `abdullah`, `fahad`, `sultan` (male); `lulwa`, `noura`, `aisha` (female).
- Default voice: none (voice is required). Custom voices: not documented (UNVERIFIED).

## WebSocket / input streaming
- None found for TTS on Groq. UNVERIFIED (no doc page located).

## Usage reporting
- Not documented in the speech response (raw audio body). UNVERIFIED for headers. Billing is per input character.

## Pricing (list price, pay-as-you-go/API)
- Unit: per 1M input characters.
- `canopylabs/orpheus-v1-english`: $22.00 per 1M characters (45,454 chars per $1). https://console.groq.com/docs/model/canopylabs/orpheus-v1-english
- `canopylabs/orpheus-arabic-saudi`: $40.00 per 1M characters (24,999 chars per $1). https://console.groq.com/docs/model/canopylabs/orpheus-arabic-saudi
- Checked 2026-10-13.

## Errors
- Codes listed: 400, 403, 404, 413, 422, 424, 429, 498 (flex tier at capacity), 499 (cancelled), 500, 502, 503. 401 is not listed. https://console.groq.com/docs/errors
- Body: `{"error":{"message":"...","type":"invalid_request_error"}}`.
