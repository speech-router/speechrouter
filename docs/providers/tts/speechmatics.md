# Speechmatics TTS

## Status
- Docs say TTS "is currently in preview and free to use"; features/pricing may change. Quickstart still says this as of 2026-10-13 (it still mentions pricing "announced September 2025, billing from Oct 1", which is stale). https://docs.speechmatics.com/text-to-speech/quickstart
- The pricing page now lists a TTS price (below), so billing exists or is planned; whether the API is GA: UNVERIFIED.
- Host is `preview.tts.speechmatics.com`. English only. No deprecations found.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://preview.tts.speechmatics.com/generate/<voice_id>`
- Auth: `Authorization: Bearer <API_KEY>`; `Content-Type: application/json`.
- Body: only `{"text": "..."}`. No model, speed, pitch, language or style fields.
- Query: `output_format` = `wav_16000` (default) or `pcm_16000`.
- Response: binary audio bytes, playable as it arrives (first chunk typically <200 ms). Not base64, not JSON.
```
curl -X POST "https://preview.tts.speechmatics.com/generate/sarah?output_format=pcm_16000" \
  -H "Authorization: Bearer $SPEECHMATICS_API_KEY" -H "Content-Type: application/json" \
  -d '{"text":"Welcome to the future of speech technology!"}' --output out.pcm
```

## Output formats
- `pcm_16000`: raw PCM, 16 kHz, 16-bit signed, mono, little-endian, no header.
- `wav_16000`: WAV with header, 16 kHz, 16-bit, mono.
- mp3, opus/ogg, mulaw/alaw: not offered.

## Models
- No model id parameter; single unnamed model. Model names: UNVERIFIED (none documented).

## Voices
- Path parameter `<voice_id>`: `sarah` (EN female UK), `theo` (EN male UK), `megan` (EN female US), `jack` (EN male US). Only 4 documented.
- No list endpoint documented. Default: none (path-required). Custom voices: not documented.

## WebSocket / input streaming
- Not supported ("streaming output is supported, but not bidirectional streaming").

## Usage reporting
- No usage fields in response (raw bytes). No webhooks.

## Pricing (list price, pay-as-you-go/API)
- Unit: per 1,000 characters. $0.011 per 1,000 characters ($11 per 1M); first 1M characters free (about 20 hours of speech). Credits shared with STT (1 credit = $1). https://www.speechmatics.com/pricing (checked 2026-10-13). Docs quickstart says preview/free: conflicting, so treat as UNVERIFIED which applies to the preview host.

## Errors
- No error table. Non-200 status plus response text; rate limits: retry with exponential backoff. Body shape: UNVERIFIED.
