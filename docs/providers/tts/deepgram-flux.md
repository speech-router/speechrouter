# Deepgram Flux TTS

Checked 2026-10-13 against https://developers.deepgram.com/docs/flux-tts/* (overview, quickstart, feature-overview, state, voices, batch, interrupt-handling), https://developers.deepgram.com/reference/text-to-speech/speak-flux.md, https://developers.deepgram.com/reference/api-rate-limits.md, https://deepgram.com/pricing.

## Status
GA (a Deepgram "what ships at GA" post exists). English only. Served only on `/v2/speak`; `/v1/speak` does not serve Flux voices (per search snippet, UNVERIFIED on the official page).

## REST endpoint (batch)
- `POST https://api.deepgram.com/v2/speak?model=flux-haley-en`
- Headers: `Authorization: Token <DEEPGRAM_API_KEY>`, `Content-Type: application/json`.
- Body: `{"text":"..."}` only. EVERYTHING ELSE IS QUERY PARAMS: `model` (required), `encoding` (default `mp3`; mp3, opus, flac, aac, linear16, mulaw, alaw), `container` (e.g. wav for linear16, ogg for opus), `bit_rate` (mp3: 8000,16000,24000,32000,40000,48000), `sample_rate` (linear16/flac 8000-48000; mulaw/alaw 8000,16000; not used for mp3/opus), `speed` (0.5-1.5 step 0.05), `expressivity` (-2..2 beta), `callback`, `callback_method` (POST|PUT), `priority` (`Low`), `tag` (repeatable), `mip_opt_out`.
- Response: raw audio bytes in the requested encoding; per-request info (character counts, `dg-warnings`) in response HEADERS. Exact header names UNVERIFIED. No language param (language is in the model string).

## WebSocket endpoint
- `wss://api.deepgram.com/v2/speak?model=flux-haley-en`
- Auth: `Authorization: Token <key>` header on upgrade. Browser subprotocol auth (`Sec-WebSocket-Protocol: token, <key>`) is UNVERIFIED for v2.
- Config via QUERY PARAMS: `model` (required), `encoding` (default `linear16`; linear16|mulaw|alaw), `sample_rate` (linear16: 8000,16000,24000,32000,44100,48000; mulaw/alaw: 8000,16000; default model native, value UNVERIFIED), `speed`, `expressivity`, `mip_opt_out`, `tag`. Batch-only params (`container`, `bit_rate`, `callback`, `callback_method`, `priority`, mp3/opus/flac/aac) are rejected. Bad `expressivity` gives HTTP 400 before upgrade.
- Audio: BINARY frames. Control: JSON text frames both ways.
- Client -> server:
  - `{"type":"Speak","text":"..."}` (server adds no whitespace between Speaks; no client-set id)
  - `{"type":"Flush"}` ends the turn (no active turn: `NO_ACTIVE_SPEECH` warning)
  - `{"type":"Interrupt","playback_offset":{"type":"time_ms","value":1500}}` (`playback_offset` optional; value = cumulative ms of session audio played since session start, must strictly advance across interrupts). NOTE: it is an object, not a number. (A Go SDK PR used `time_ms`; the reference confirms the object form.)
  - `{"type":"Configure","speed":1.1}` (0.5-1.5, multiple of 0.05; applies at next segment boundary)
  - `{"type":"Close"}` drains queued audio, sends SessionMetadata, closes
- Server -> client:
  - `{"type":"Connected","request_id":"uuid","model_name":"...","model_version":"...","model_uuids":["uuid"]}`
  - `{"type":"SpeechStarted","speech_id":"dg_sp_<12hex>"}` (once per turn, on first Speak)
  - `{"type":"Flushed","speech_id":"..."}` (may be delayed behind earlier pending turns)
  - `{"type":"SpeechMetadata","speech_id","audio_duration_ms","input_character_count","billable_character_count","controls_applied":{"pronunciations_applied","breaks_applied","pronunciation_warnings"}}` (turn end, after Flush)
  - `{"type":"SpeechInterrupted","audio_played_ms":int,"text_spoken":"...","text_remaining":"...","metadata":{"speech_id","audio_duration_ms","input_character_count","billable_character_count","controls_applied":{...}}}` (`text_spoken`/`text_remaining` omitted if no `playback_offset`; no separate SpeechMetadata for an interrupted turn)
  - `{"type":"SessionMetadata","total_audio_duration_ms","total_input_character_count","total_billable_character_count"}` (final, before close; interrupts can reduce totals)
  - `{"type":"ConfigureSuccess","applied":{"speed":1.1}}`
  - `{"type":"ConfigureFailure","code":"SPEED_OUT_OF_RANGE|SPEED_INCREMENT_INVALID|SPEED_NOT_SUPPORTED|CONTROL_COMBINATION_INVALID|INTERNAL_ERROR","field":"speed","value":2.0,"description":"..."}` (prior config kept)
  - `{"type":"Warning","code":"...","description":"..."}` non-fatal. Codes: NO_ACTIVE_SPEECH, NO_SYNTHESIZABLE_TEXT, SYNTHESIS_RETRYING, PRONUNCIATION_WARNINGS, PRONUNCIATION_TOO_LONG, PRONUNCIATIONS_LIMIT_EXCEEDED, NO_AUDIO_GENERATED, INTERRUPT_IN_PROGRESS, INVALID_INTERRUPT_OFFSET (interrupt-scoped ones mean Interrupt ignored), INPUT_MARKUP_STRIPPED.
  - `{"type":"Error","code":"MESSAGE-0000|DATA-0000|DATA-0002|BIG-0000|NET-0000|NET-0001|NET-0002|NET-0003|NET-0004","description":"..."}` fatal, then socket closes.
- Turn model: one active turn; later Speaks after Flush queue as pending turns (unbounded, in order); each turn new `speech_id`. Turn ends on `Flush` -> `Flushed` + `SpeechMetadata`. Server places internal flush boundaries too. The single `Speak`-stream turn is also what the cross-turn prosody context uses.
- Barge-in procedure: stop local playback, send `Interrupt` with session-wide playback counter, discard audio arriving until `SpeechInterrupted`, append `text_spoken` to LLM history. Interrupt does not reset voice state.

Example session:
```
C: GET wss://api.deepgram.com/v2/speak?model=flux-haley-en&encoding=linear16&sample_rate=24000
S: {"type":"Connected","request_id":"...","model_name":"flux-haley-en","model_version":"...","model_uuids":["..."]}
C: {"type":"Speak","text":"Sure, "}
C: {"type":"Speak","text":"I can help you cancel your subscription."}
S: {"type":"SpeechStarted","speech_id":"dg_sp_a1b2c3d4e5f6"}
S: <binary audio frames>
C: {"type":"Interrupt","playback_offset":{"type":"time_ms","value":1500}}
S: {"type":"SpeechInterrupted","audio_played_ms":1500,"text_spoken":"Sure, I can help","text_remaining":" you cancel your subscription.","metadata":{"speech_id":"dg_sp_a1b2c3d4e5f6","audio_duration_ms":3200,"input_character_count":47,"billable_character_count":47,"controls_applied":{"pronunciations_applied":0,"breaks_applied":0,"pronunciation_warnings":0}}}
C: {"type":"Speak","text":"Okay."}
C: {"type":"Flush"}
S: {"type":"SpeechStarted","speech_id":"dg_sp_0123456789ab"}
S: {"type":"Flushed","speech_id":"dg_sp_0123456789ab"}
S: <binary audio>
S: {"type":"SpeechMetadata","speech_id":"dg_sp_0123456789ab",...}
C: {"type":"Close"}
S: {"type":"SessionMetadata","total_audio_duration_ms":...,"total_input_character_count":...,"total_billable_character_count":...}
```
(The SpeechInterrupted example values are illustrative; the Flush-only transcript shape is from the state docs.)

## Models
Model id = `flux-{voice}-{language}`; only language is `en`. Required on every connection.

## Voices (all English; 36 listed, first 20 shown)
flux-hannah-en, flux-kit-en, flux-alexis-en, flux-cliff-en, flux-sienna-en, flux-cole-en, flux-brooke-en, flux-colin-en, flux-gemma-en, flux-haley-en, flux-heather-en, flux-miles-en, flux-sean-en, flux-bree-en, flux-brittany-en, flux-bruce-en, flux-conor-en, flux-donovan-en, flux-drew-en, flux-elise-en. Also: jack, kai, kelsey, maeve, marcelo, marcus, meena, meghan, naveen, paige, priya, rufus, sharon, tanner, wade, wes (same `flux-<name>-en` pattern). Accents: American, British, Irish, Australian, Indian, Singaporean, Filipino. Source: /docs/flux-tts/voices.md. No voice-list API found (UNVERIFIED).

## Formats / rates
WS: linear16 (8000, 16000, 24000, 32000, 44100, 48000), mulaw/alaw (8000, 16000). Batch adds mp3 (default), opus, flac, aac. linear16 is presumably s16le (UNVERIFIED).

## Usage / billing reporting
In-band: `SpeechMetadata` / `SpeechInterrupted.metadata` give `audio_duration_ms`, `input_character_count`, `billable_character_count` per turn; `SessionMetadata` gives session totals. Batch: response headers (names UNVERIFIED). `tag` query param labels usage.

## Pricing
Flux TTS $0.0450 per 1,000 chars PAYG ($0.0405 Growth); Aura-2 $0.030. Promo: $1 credit per $1 spent up to $500 through 2026-12-31. Source https://deepgram.com/pricing, checked 2026-10-13. Confirms existing survey.

## Limits
Session max 1 hour (server closes). Inactivity 60 s without inbound client message -> `NET-0004`; WebSocket Ping/Pong resets. Concurrency per project, streaming PAYG: 45 NA / 5 EU,AU,IN; Growth 60 NA / 5 others; Enterprise start 100 NA / 50 others. REST concurrency 15 NA / 5 others (25 enterprise). Chars per request/Speak message: not stated (UNVERIFIED; `BIG-0000` is the oversized-message error). Speed unsupported for some models: `SPEED_NOT_SUPPORTED`.

## Errors
WS: fatal `Error` JSON with code above then close; non-fatal `Warning`; pre-upgrade HTTP 400 for invalid query params. Mapping of each Error code to cause is only partially documented (NET-0004 inactivity, 1-hour limit code UNVERIFIED which). REST error JSON shape UNVERIFIED (only `SPEED_NOT_SUPPORTED` named).
