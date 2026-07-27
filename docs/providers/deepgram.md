# Deepgram — protocol brief (verified 2026-07-27)

## Realtime v1 WS: `wss://api.deepgram.com/v1/listen?<params>`
- Auth: `Authorization: Token <KEY>` (scheme is **Token**, not Bearer). Short-lived JWT via `POST /v1/auth/grant` (default TTL 30s) → `Authorization: Bearer <JWT>`; browser: WS subprotocol `['token', KEY]`.
- Params: `model` (nova-3 flagship, nova-3-medical, nova-2*, NO nova-4), `encoding` (linear16, linear32, flac, alaw, mulaw, amr-*, opus, ogg-opus, speex, g729 — REQUIRED for raw, omit for containerized), `sample_rate` (required w/ encoding), `channels`+`multichannel`, `interim_results` (default false; required true for utterance_end_ms), `endpointing` (ms, default 10), `utterance_end_ms` (min 1000), `vad_events`, `diarize` (**deprecated → `diarize_model`**), `keyterm` (nova-3/flux, plain strings, repeatable, 500-token cap) vs `keywords` (`word:boost`, nova-2 and older ONLY — route by model family!), `language` (BCP-47, `multi` on nova-3), `smart_format`, `punctuate`, `callback`
- Audio: binary frames; control JSON: TEXT frames (binary JSON → treated as audio → DATA-0000). Raw + wrong encoding/sample_rate fails SILENTLY. Chunks 20–250ms.

## Results message
`{type:"Results", channel_index:[0,1], start, duration, is_final, speech_final, from_finalize, channel:{alternatives:[{transcript, confidence, languages[], words:[{word, start, end, confidence, language, punctuated_word?, speaker?}]}]}, metadata:{request_id, model_info}}`
- **is_final** = text frozen for that audio range (accuracy-driven, can fire MID-utterance). **speech_final** = endpointer silence fired (end of utterance). Long utterance → multiple `is_final,speech_final:false` then one `speech_final:true`. NEVER use speech_final alone; concatenate is_final segments until speech_final.
- `UtteranceEnd` {channel:[i,n], last_word_end} (needs utterance_end_ms + interim_results; `last_word_end:-1` = already-finalized sentinel). `SpeechStarted` {timestamp} (vad_events). `Metadata` at stream end.
- Timestamps: float SECONDS from stream start.

## Control (text frames)
- `{"type":"KeepAlive"}` — every **3–5s** during silence or close 1011/NET-0001 at ~10s. KeepAlive alone won't hold forever: NET-0002 `no_audio_timeout` eventually.
- `{"type":"Finalize"}` — flush; MAY get Results with `from_finalize:true` (NOT guaranteed — don't block on it).
- `{"type":"CloseStream"}` — flush → final Results → Metadata → close. (Replaced empty-binary-frame convention.)

## Flux (SEPARATE v2 protocol, conversational/turn-based)
- `wss://api.deepgram.com/v2/listen?model=flux-general-en|flux-general-multi`
- Params: encoding (linear16/32, mulaw, alaw, opus, ogg-opus only), sample_rate (16k rec), `eot_threshold` (0.5-0.9 def 0.7), `eager_eot_threshold` (0.3-0.9), `eot_timeout_ms` (def 5000), keyterm, language_hint. NO interim_results/endpointing/utterance_end.
- 80ms chunks recommended. Every message has `sequence_id`.
- Server: `Connected`, `TurnInfo` {event: **Update|StartOfTurn|EagerEndOfTurn|TurnResumed|EndOfTurn**, turn_index, audio_window_start/end, transcript, words[{word,confidence,start,end}], end_of_turn_confidence}, `ConfigureSuccess/Failure`, `Error` {code, description}.
- Client: binary audio, `{"type":"CloseStream"}`, mid-stream `{"type":"Configure",...}`. NO documented KeepAlive.

## Batch POST /v1/listen
- Body: raw binary + Content-Type audio/*, OR JSON `{"url": ...}`. Sync default (**response is the ONLY chance to get transcript — Deepgram stores nothing**); async via `callback` → `{request_id}`.
- 2 GB max; 10-min processing timeout (20 for whisper) → 504.

## Errors / limits
- 1008/DATA-0000 undecodable audio; 1011/NET-0000 server; NET-0001 client silent 10s; NET-0002 no audio.
- Concurrency per project: streaming 150 (PAYG); prerecorded 50.

## Pricing (2026-07 — REPRICED, streaming now CHEAPER than batch)
- Nova-3 mono: stream $0.0048/min, batch $0.0077/min. Nova-3 multi: $0.0058 / $0.0092. Flux EN $0.0065/min, multi $0.0078 (streaming only). Rounding increment unpublished — verify before billing reconciliation.
