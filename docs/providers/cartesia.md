# Cartesia — STT protocol brief (verified 2026-07-27)

Models: **ink-2** (flagship 2026-05-22, EN-only, built-in turn detection), **ink-whisper** (legacy, ~99 langs). Version pin: `cartesia_version=2026-03-01` (query) / `Cartesia-Version` header (REST).

## Realtime — TWO WS endpoints

### A. Turns WS (ink-2, server-driven turns): `wss://api.cartesia.ai/stt/turns/websocket`
- Auth: `X-API-Key` header / `access_token` query (browser)
- Required: model=ink-2, encoding (pcm_s16le|s32le|f16le|f32le|mulaw|alaw), sample_rate, cartesia_version
- Optional: turn_start_threshold (def 0.8), turn_eager_end_threshold (def 0.4), turn_end_threshold (def 0.2), turn_end_timeout_ms (def 5600), keyterm (≤100 terms)
- Client: binary audio ~100ms chunks; `{"type":"close"}`; mid-session `{"type":"config","turn":{...}}`
- Server: `connected`, `turn.start`, `turn.update` {transcript}, `turn.eager_end` {transcript} (LLM head-start), `turn.resume` (eager was wrong), `turn.end` {transcript}, `error` {title,message,error_code,status_code}
- **All text final (no revisions); transcript CUMULATIVE within turn. No word timestamps. No finalize command.**

### B. Classic WS (manual control, both models): `wss://api.cartesia.ai/stt/websocket`
- Same auth; + `language` (ink-whisper), min_volume/max_silence_duration_secs (ink-whisper only), keyterm (ink-2 only)
- Client: binary audio; **plain-text string commands** `finalize` and `close` (NOT JSON!)
- Server: `{"type":"transcript","is_final":true,"request_id","text","duration","words":[{word,start,end}]}` — **text is a DELTA from last finalized chunk; concatenate is_final chunks verbatim (don't touch whitespace)**; `flush_done` (finalize ack), `done` (close ack), `error`

## Batch: POST https://api.cartesia.ai/stt
Multipart, Bearer sk_car_..., model=**ink-whisper only** (no ink-2 batch), timestamp_granularities ["word"] only. Response {type:"transcript", text, language, duration, words[]}.

## Pricing (credits)
ink-2 stream 3 credits/sec; ink-whisper stream 1/sec (~$0.13/hr Scale); ink-whisper batch 1 per 2sec.
