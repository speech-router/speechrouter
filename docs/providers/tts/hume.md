# Hume - Octave TTS

## Status
- SUNSETTING: Hume announced 2026-10-02 that the TTS (Octave) and EVI APIs end 2026-11-13 12:01 a.m. EST; account data deleted after. Stated in https://dev.hume.ai/docs/text-to-speech-tts/overview (and confirmed via search snippets of Hume docs). Do not build a production integration; at most a short-lived provider.
- API currently live until that date (status incident 2026-07-11 resolved: https://status.hume.ai/incidents/01KXGYW43SFEGE03DN0JVDTY7V).

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.hume.ai/v0/tts/stream/file` (continuous stream of raw audio bytes, e.g. `audio/mpeg`) - https://dev.hume.ai/reference/text-to-speech-tts/synthesize-file-streaming
- Also: `POST /v0/tts/stream/json` (stream of JSON objects with base64 audio + metadata), `/v0/tts` (JSON base64), `/v0/tts/file` (non-stream file).
- Auth: `X-Hume-Api-Key: <key>`; `Content-Type: application/json`.
- Body: `utterances[]` {`text` (required), `description`, `speed` (default 1; <0.75 or >1.5 unstable), `trailing_silence`, `voice`}, `context`, `format` (default `{"type":"mp3"}`), `include_timestamp_types` (Octave 2), `num_generations`, `split_utterances` (default true), `strip_headers` (default false), `temperature`, `version` ("1" or "2"; 2 requires voice), `instant_mode` (default true; needs voice + 1 generation).
- Voice ref: `{"name":"...","provider":"HUME_AI"|"CUSTOM_VOICE"}` or `{"id":...}`; default provider CUSTOM_VOICE.
- Language: no language field documented; Octave 1 English+Spanish, Octave 2 11 languages (preview).
- Limits: 5,000 chars text and 1,000 chars description per utterance; up to 5 generations.
- Example:
  ```
  curl -X POST https://api.hume.ai/v0/tts/stream/file -H "X-Hume-Api-Key: $HUME_API_KEY" -H "Content-Type: application/json" \
   -d '{"utterances":[{"text":"Hello there.","voice":{"name":"Male English Actor","provider":"HUME_AI"}}],"format":{"type":"pcm"},"strip_headers":true}' -o out.pcm
  ```

## Output formats
- `format.type`: `mp3`, `pcm`, `wav` only (docs). Opus/ogg, mulaw/alaw: not offered.
- PCM sample rate and bit depth: UNVERIFIED (not stated). `strip_headers: true` concatenates chunk audio into one file.

## Models / voice families
- Octave 1 (`version: 1`): English, Spanish, ~200 ms; Octave 2 (`version: 2`, preview): 11 languages, ~100 ms, requires a voice, timestamps (word/phoneme).
- Voice Design (text prompt) and Voice Cloning (>=15 s). https://dev.hume.ai/docs/text-to-speech-tts/overview

## Voices
- Referenced by `name` or `id` with provider `HUME_AI` (library) or `CUSTOM_VOICE`.
- Verified name: `Male English Actor` (provider HUME_AI). List endpoint URL: UNVERIFIED (not read). Other popular names: UNVERIFIED.
- Default suggestion: `{"name":"Male English Actor","provider":"HUME_AI"}`.
- Custom voices: yes (design/clone).

## WebSocket / input streaming
- `/v0/tts/stream/input` WebSocket: send text incrementally, receive audio on the same connection (full URL scheme/params UNVERIFIED). Instant mode ~1 s sub-snippet chunks, first audio ~200 ms.

## Usage reporting
- Not documented in pages read: UNVERIFIED.

## Pricing (list price, pay-as-you-go)
- Hume pricing pages did not render (www.hume.ai/pricing had no Octave info; link.hume.ai/pricing empty). Per-character/overage rates: UNVERIFIED. Billing unit: UNVERIFIED. Checked 2026-10-13.

## Credentials
- Single Hume API key (`X-Hume-Api-Key`).

## Errors
- 422 validation: body `detail[]` items with `loc`, `msg`, `type`. Other codes (401/429) and shapes: UNVERIFIED.
