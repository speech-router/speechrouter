# Rime TTS

## Status
- Public API live. Current models: Coda (flagship, released May 2026) and Mist v3 (March 2026); Mist v1/v2 legacy, no EOL date (https://docs.rime.ai/api-reference/models). No acquisition found.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://users.rime.ai/v1/rime-tts` (https://docs.rime.ai/api-reference/coda/http, https://docs.rime.ai/api-reference/endpoint/streaming-mp3)
- Auth: `Authorization: Bearer <API_KEY>`. Output format chosen by the `Accept` header (not the body).
- Body: `speaker` (required), `text` (required, max 1,000 chars), `modelId` (`coda` | `mistv3`; omitted/unknown -> `mistv3`, so always set), `lang` (default `en`; must match speaker), `samplingRate` (default 24000), `timeScaleFactor` (0.4-2.5, >1.0 slower, clamped), Mist v3 only: `pauseBetweenBrackets`, `inlineSpeedAlpha`. No style/instructions field.
- Response: 200, streamed raw audio bytes in the `Accept` type; not SSE/base64. Unsupported Accept -> 406 listing supported types.
- Example body: `{"speaker":"astra","text":"Hello from Rime!","modelId":"coda","lang":"en","samplingRate":24000}` with header `Accept: audio/L16`.

## Output formats
(`Accept` header)
- `audio/webm;codecs=opus` (recommended), `audio/ogg;codecs=opus`, `audio/mpeg` (mp3), `audio/wav`, `audio/L16` (headerless 16-bit PCM; endianness not stated, assume s16le - UNVERIFIED), `audio/PCMU` (G.711 mu-law headerless; 8 kHz native - set `samplingRate: 8000`).
- Deprecated aliases: `audio/mp3`, `audio/pcm`, `audio/x-mulaw`. Missing/wildcard Accept -> headerless 16-bit PCM.
- Allowed `samplingRate` values: only default 24000 and 8000 (telephony) verified; others UNVERIFIED. alaw: not offered.

## Models
- `coda` - flagship, recommended for new apps; en, ar, fr, de, hi, it, ja, pt, es; no inline pronunciation control.
- `mistv3` - low-latency; en, fr, de, es; default when modelId omitted.
- `mistv2`, `mist` - LEGACY (no EOL date).

## Voices
- Identified by speaker name string (`speaker`). Lists: `https://users.rime.ai/data/voices/voice_details.json` (per Rime search result; docs.rime.ai path 404'd) and `/data/voices/all-v2.json` (per https://docs.rime.ai/api-reference/voices). Coda catalog 287 voices, Mist v3 78.
- Verified ids: `astra` (Coda, Mist v3), `luna` (Coda, Mist v3), `celeste` (Coda), `masonry` (Coda), `albion` (Coda), `cove` (Mist v3), `lyra`, `clementine`, `lintel`, `eyre`, `bancroft`, `marlu`, `hesse`, `beatty`, `godfrey` (Coda featured).
- Default: `astra` (recommended in docs for first Coda request).
- Custom: enterprise voice clones get a UUID passed as `speaker` with `modelId: coda`; not self-serve.

## WebSocket / input streaming
- `wss://users-ws.rime.ai/ws3?speaker=astra&modelId=coda&audioFormat=mp3` with `Authorization: Bearer` header (https://docs.rime.ai/api-reference/endpoint/websockets-json). `audioFormat` e.g. `mp3`, `mulaw`.
- Client: `{"text","contextId"}`, `{"operation":"flush"|"clear"|"eos"}`. Server: `chunk` (base64 audio), `timestamps`, `done`, `error`.

## Usage reporting
- Not documented (response headers not covered). UNVERIFIED.

## Pricing (list price, pay-as-you-go/API)
Source: https://www.rime.ai/pricing - checked 2026-10-13
- Mist v3 (Starter): $0.03 per 1K characters ($30/1M). Coda (Starter): $0.05 per 1K characters ($50/1M). Enterprise custom.
- Billing unit: characters (UTF-8 bytes vs chars UNVERIFIED). Approx $0.03/min Mist v3, $0.05/min Coda as stated on page (inconsistent with per-char; use per-char). Free minutes stated inconsistently (about 800 vs 3,000).

## Errors
- Only 406 documented (unsupported Accept). Other codes and body shape UNVERIFIED. WS: `error` message, connection stays open.
