# xAI Grok TTS

Checked 2026-10-13 against https://docs.x.ai/developers/model-capabilities/audio/text-to-speech and https://docs.x.ai/developers/pricing.

## Status
Documented, generally available (no beta label seen on the page). No `model` field exists in the API. UNVERIFIED: whether a model id is exposed anywhere.

## REST endpoint
- `POST https://api.x.ai/v1/tts`, header `Authorization: Bearer $XAI_API_KEY`, `Content-Type: application/json`.
- Body (flat except `output_format` and `replace`):
  - `text` (string, required, max 60,000 chars; supports speech tags)
  - `language` (string, REQUIRED; `auto` or BCP-47, case-insensitive)
  - `voice_id` (string, default `eve`, case-insensitive; built-in or custom id). NOTE: the REST field is `voice_id`, not `voice`.
  - `output_format` (object): `{ "codec": "mp3|wav|pcm|mulaw|alaw", "sample_rate": int, "bit_rate": int }`. Defaults mp3 / 24000 / 128000. `bit_rate` is MP3 only.
  - `speed` (0.7 to 1.5, default 1.0)
  - `optimize_streaming_latency` (0, 1, 2; default 0)
  - `text_normalization` (bool, default false)
  - `with_timestamps` (bool, default false)
  - `replace` (object phrase -> spoken substitution; max 200 entries, key <=100 chars, value <=128 chars)
- Example: `{"text":"Hello!","voice_id":"ara","language":"en","output_format":{"codec":"mp3","sample_rate":44100,"bit_rate":192000},"speed":1.2}`
- Response: raw audio bytes (Content-Type per codec). With `with_timestamps:true`, JSON: `{"audio":"<base64>","content_type":"audio/mpeg","duration":0.92,"audio_timestamps":{"graph_chars":[...],"graph_times":[[start,end],...]}}` (seconds).

## WebSocket endpoint
- URL `wss://api.x.ai/v1/tts`. Auth: `Authorization: Bearer $XAI_API_KEY` on the upgrade request (server-side only; browsers cannot set it).
- Config is via QUERY PARAMS (note names differ from REST): `language` (required), `voice`, `codec` (mp3|wav|pcm|mulaw|ulaw|alaw; default mp3), `sample_rate` (default 24000), `bit_rate` (MP3 only), `speed`, `optimize_streaming_latency`, `text_normalization`, `with_timestamps`. Invalid voice/language/codec/sample_rate is rejected before upgrade with HTTP 400 or 404.
- Client -> server (JSON text frames):
  - `{"type":"text.delta","delta":"..."}` (max 60,000 chars each)
  - `{"type":"text.done"}` ends the utterance
  - `{"type":"text.clear"}` barge-in / cancel
  - `{"type":"session.update","replace":{"Acme Mobile":"Acme Mobull"}}` (applies from next utterance)
- Server -> client (JSON text frames; audio is BASE64 in JSON, never binary):
  - `{"type":"audio.delta","delta":"<base64>"}` (with `with_timestamps=true` also carries `audio_timestamps` {graph_chars, graph_times} and `audio_duration`)
  - `{"type":"audio.done","trace_id":"uuid"}` end of utterance
  - `{"type":"audio.clear"}` reply to `text.clear` (immediate if nothing in progress)
  - `{"type":"session.updated","replace":{...}}`
  - `{"type":"error","message":"description"}` (invalid `replace` map: error, old map kept, connection stays open; utterance >240,000 chars after substitution ends the session)
- Connection stays open across utterances; each turn independent. No per-message ids or sequence numbers; only `trace_id` on `audio.done`.
- Barge-in: send `text.clear`, drop local playback buffer on `audio.clear`, then send new `text.delta` + `text.done`. Audio already in flight before the clear may still arrive until `audio.clear` (UNVERIFIED ordering).

Example session:
```
C: GET wss://api.x.ai/v1/tts?language=en&voice=eve&codec=pcm&sample_rate=24000
C: {"type":"text.delta","delta":"Hello there. "}
C: {"type":"text.delta","delta":"How can I help?"}
C: {"type":"text.done"}
S: {"type":"audio.delta","delta":"UklGR..."}
S: {"type":"audio.delta","delta":"AAAA..."}
S: {"type":"audio.done","trace_id":"3f1c...-uuid"}
C: {"type":"text.delta","delta":"Second turn, interrupted."}
C: {"type":"text.clear"}
S: {"type":"audio.clear"}
```

## Models
No model id. UNVERIFIED beyond that.

## Voices
Default `eve`; `ara`, `rex` named on the page. Full built-in list is NOT on the docs page: `GET https://api.x.ai/v1/tts/voices` (Bearer) returns `{"voices":[{"voice_id","name"}...]}`. Custom voices: `GET /v1/custom-voices`. UNVERIFIED: other built-in ids (the prior survey's "rex..." list could not be confirmed beyond eve/ara/rex).

Languages: auto, en, ar-EG, ar-SA, ar-AE, bn, zh, fr, de, hi, id, it, ja, ko, pt-BR, pt-PT, ru, es-MX, es-ES, tr, vi. Any voice speaks any language.

## Formats / rates
codec: `mp3` (audio/mpeg), `wav` (audio/wav), `pcm` (audio/pcm), `mulaw` (audio/basic), `alaw` (audio/alaw). sample_rate: 8000, 16000, 22050, 24000 (default), 44100, 48000. bit_rate (mp3): 32000, 64000, 96000, 128000, 192000. UNVERIFIED: pcm sample width/endianness (presumably s16le).

## Usage / billing reporting
Not documented: no usage headers or message fields found. WS billing is "recorded per session based on total input characters"; REST bills the original text (pre-`replace`). `trace_id` on `audio.done` is the only identifier.

## Pricing
$15.00 / 1M characters ("Text to Speech", Voice Pricing table). Source https://docs.x.ai/developers/pricing, checked 2026-10-13. Confirms existing survey.

## Limits
REST: 60,000 chars/request, 15 min timeout, concurrency not stated. WS: no total limit, 60,000 chars per delta, 50 concurrent sessions per team, session permit TTL 600 s (meaning UNVERIFIED: whether sessions are cut at 600 s), no idle timeout stated. Text after `replace` <=240,000 chars. WS moderation runs asynchronously after audio is sent, fails open. TTS-specific rate limits UNVERIFIED.

## Errors
REST HTTP: 400 bad request (empty/oversize text, bad codec/rate), 401, 404 unknown voice_id, 429, 500, 503. Error body shape UNVERIFIED. WS: `{"type":"error","message":"..."}`; pre-upgrade failures are HTTP 400/404.
