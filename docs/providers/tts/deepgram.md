# Deepgram Aura TTS

## Status
- Public TTS API live (https://developers.deepgram.com/docs/text-to-speech). Aura-2 and Aura-1 both offered and priced; no deprecation notice on the models page (https://developers.deepgram.com/docs/tts-models). No acquisition found.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.deepgram.com/v1/speak`
- Auth: `Authorization: Token <DEEPGRAM_API_KEY>`; `Content-Type: application/json`.
- Query params (https://developers.deepgram.com/reference/text-to-speech/speak-request): `model` (default `aura-asteria-en`), `encoding`, `container`, `sample_rate` (default 24000), `bit_rate`, `callback`, `callback_method`, `mip_opt_out`, `tag`. Speed param exists on the WebSocket (`speed` 0.7-1.5); on REST UNVERIFIED.
- Body: `{"text": "..."}` only. No language/style fields (language is encoded in the model id). Max 2,000 chars per request (413 if longer).
- Response: 200, raw audio bytes, `transfer-encoding: chunked`; not SSE/JSON. Content-Type depends on encoding (see below).
- Example: `POST /v1/speak?model=aura-2-thalia-en&encoding=linear16&container=none&sample_rate=24000` body `{"text":"Hello, how can I help you today?"}`
- Docs defaults: REST `linear16`/`wav`/24000 (the reference page says encoding default `mp3`; the two pages conflict - always pass explicit params).

## Output formats
(https://developers.deepgram.com/docs/tts-media-output-settings)
- `encoding=linear16`: container `wav` (default) or `none`; sample_rate 8000, 16000, 24000 (default), 32000, 48000. Raw PCM s16le: `encoding=linear16&container=none` (Content-Type `audio/l16;rate=N`).
- `mulaw`: container `wav`|`none`; sample_rate 8000 (default), 16000. `alaw`: same.
- `mp3`: fixed 22050 Hz, bit_rate 32000|48000 (default).
- `opus`: container `ogg`, fixed 48000, bit_rate default 12000 (4000-650000).
- `flac`: 8000, 16000, 22050, 32000, 48000. `aac`: fixed 22050, bit_rate default 48000 (4000-192000).
- Streaming (WebSocket) supports only linear16, mulaw, alaw.
- For telephony use `container=none` (WAV header can cause clicks).

## Models
- Format `[family]-[voice]-[lang]`. Default `aura-asteria-en` (Aura-1). Aura-1 (12 English voices) and Aura-2 (~90 voices: en, es, nl, fr, de, it, ja).
- Aura-2 e.g. `aura-2-thalia-en`, `aura-2-andromeda-en`, `aura-2-helena-en`, `aura-2-apollo-en`, `aura-2-arcas-en`, `aura-2-aries-en`. Aura-1 e.g. `aura-asteria-en`, `aura-luna-en`, `aura-orion-en`.
- The "model" and the voice are the same string. No deprecated models stated.

## Voices
- No separate voice id: the `model` string selects the voice. List: https://developers.deepgram.com/docs/tts-models (docs page; no list endpoint found - UNVERIFIED).
- Aura-2 ids: `aura-2-thalia-en`, `aura-2-andromeda-en`, `aura-2-helena-en`, `aura-2-apollo-en`, `aura-2-arcas-en`, `aura-2-aries-en`, `aura-2-celeste-es`, `aura-2-estrella-es`, `aura-2-nestor-es`, `aura-2-agathe-fr`, `aura-2-hector-fr`, `aura-2-julius-de`, `aura-2-viktoria-de`, `aura-2-livia-it`, `aura-2-fujin-ja`.
- Aura-1 ids: `aura-asteria-en` (en-us), `aura-luna-en`, `aura-stella-en`, `aura-athena-en` (en-gb), `aura-hera-en`, `aura-orion-en`, `aura-arcas-en`, `aura-perseus-en`, `aura-angus-en` (en-ie), `aura-orpheus-en`, `aura-helios-en` (en-gb), `aura-zeus-en`.
- Default: `aura-2-thalia-en` (used in official examples); API default is `aura-asteria-en`.
- Arbitrary custom/cloned ids: not offered in docs read (UNVERIFIED).

## WebSocket / input streaming
- `wss://api.deepgram.com/v1/speak` (https://developers.deepgram.com/reference/text-to-speech/speak-streaming). Query: `model`, `encoding` (linear16|mulaw|alaw), `sample_rate` (8000/16000/24000/32000/48000), `speed` 0.7-1.5.
- Client JSON messages: Speak (text), Flush, Clear, Close. Server: binary Audio frames, JSON Metadata, Flushed, Cleared, Warning.

## Usage reporting
- Yes, response headers: `dg-char-count` (input characters), `dg-model-name`, `dg-model-uuid`, `dg-request-id`.

## Pricing (list price, pay-as-you-go/API)
Source: https://deepgram.com/pricing - checked 2026-10-13
- Aura-2: $0.030 per 1K characters ($30/1M). Aura-1: $0.0150 per 1K characters ($15/1M).
- Billing unit: characters of input text (matches `dg-char-count`; whitespace/bytes handling UNVERIFIED).

## Errors
- 400 invalid request; 413 text over 2,000 chars (no audio); 422 unprocessable; 429 concurrency limit reached (https://developers.deepgram.com/docs/text-to-speech). Others (401/402) UNVERIFIED.
- Body: modern `{"category","message","details","request_id"}` or legacy `{"err_code","err_msg","request_id"}` (https://developers.deepgram.com/reference/text-to-speech/speak-request).
