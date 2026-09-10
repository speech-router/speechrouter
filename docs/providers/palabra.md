# Palabra — STT protocol brief (verified 2026-08-13)

Docs: docs.palabra.ai (`/docs/auth`, `/docs/streaming_api/realtime_stt`).
Cross-checked against the official SDK, `github.com/PalabraAI/palabra-ai-python` v2.1.0 (`src/palabra_ai/{client,stt,events,audio}.py`) — every claim below that the docs left implicit is marked *(SDK)*.

Palabra builds its own STS, STT and TTS stack; each is a first-class API. This adapter uses the **STT one — a standalone WebSocket that needs no session brokering**. The STS lane (session API, WebRTC rooms, output audio) and the TTS lane are out of scope: this repo has no translation event and no `/v1/speak`.

## Realtime WS
- Endpoint: `wss://stream.palabra.ai/asr/v1/speech-to-text/stream`
- **Endpoints are per-region** *(SDK)*. Regions `eu` (default) and `us`; **STT exists only in `eu` today** — `us` currently carries TTS alone. Hardcoding the `eu` host is fine for v1, but the adapter should keep the host in one constant, not inline.
- Auth: API key as `token` query param, or `Authorization: Bearer <key>` header on the upgrade. Server-side only.
- **No session create step, no config frame.** Server creates the session for the lifetime of the connection and cleans it up when the connection ends — so `close()` has nothing to delete upstream.
- Query: `token` (req), `format` (req), `sample_rate` (req for raw PCM unless 16000, and for mulaw/alaw; omit → server assumes 16000), `language` (def auto), `translate_languages` (csv e.g. `es,de,fr`), `enable_filler_filter` (def on, except `ja`)
- Audio: raw binary frames. **320ms chunks, paced to realtime — the SDK's pacer says the server requires it** *(SDK)*, and the wire has `AUDIO_STREAM_TOO_FAST` / `TOO_SLOW` / `STALLED` warning codes to enforce it.
- Formats: `pcm_s16le` (recommended), `pcm_s32le|be`, `pcm_f32le|be`, `mulaw`, `alaw`; containers aac flac mp3 ogg wav webm. Ours→theirs: linear16→`pcm_s16le`, linear32→`pcm_s32le`, mulaw, alaw.
- Liveness: the SDK dials with `ping_interval=10, ping_timeout=30, max_size=None` *(SDK)* — **standard WS ping/pong, not an app-level keepalive frame.** Do not copy Telnyx's `ping_interval=None` here.

```
wss://stream.palabra.ai/asr/v1/speech-to-text/stream
  ?token=<API_KEY>&language=en&format=pcm_s16le&sample_rate=16000
```

## Response
JSON text frames keyed by `message_type`.

`transcription`: `{message_type, transcription_id, language, is_eos, segment:{text,start_time,end_time}, delta:{text,start_time,end_time}}`
- `is_eos` false→partial, true→final. `transcription_id` groups the partials + final of one segment. Times in **seconds** (not ms).
- **Read `segment.text`, ignore `delta`** — delta semantics flip with `enable_filler_filter`: filter off → `delta.text` append-only; filter on → `segment.text` authoritative, overwrite. Filter defaults ON, so segment is correct either way.
- **No word timestamps, no confidence, no speaker labels** — segment-level only → `words=None`, diarization False (resolver rejects `diarization=true` before dialing).

`translated_transcription`: same shape minus `delta`; only when `translate_languages` is set, emitted after the source final; `transcription_id` matches the source. Live-confirmed working upstream — `translate_languages=es` returns clean Spanish finals per utterance.

**Delivered, with a documented timestamp nudge.** *(live 2026-08-13)* A translated final carries the **same `end` timestamp** as the source final it belongs to, and arrives after it. `router/session.py` `_normalize()` drops any final whose end does not advance past `_last_final_end`, so a verbatim translated final never reaches the client.

Failover dedup depends on that invariant, so the adapter does not weaken it. Instead it advances the translated final's `end` by 1ms per target language, in the order the caller listed them in `translate_languages` (`es` → +0.001, `de` → +0.002):

- finals only, since partials never reach the dedup gate;
- deterministic: a replay after failover reproduces the same `end` and stays deduped;
- the offset is a few ms on a timestamp that is a copy of the source segment's.

The clean fix is a dedicated translation event in `packages/spec`; this keeps translation deliverable until that lands, without touching the session engine.

**Do not confuse this with the S2S wire.** The translation lane uses different message types (`partial_transcription`, `validated_transcription`, `partial_translated_transcription`) with the payload nested under `data.transcription` *(SDK `events.py`)*. The STT lane is flat: top-level `segment`, finality via `is_eos`. Sample payloads found online are usually the S2S shape and do not apply here.

## Control / shutdown
- **The STT lane has no finalize, no EOS, no CloseStream** — the SDK's `SttSession` exposes only `send_audio`/`close` *(SDK)*. Closing the socket is the only way to end it.
- Contrast: the S2S lane *does* have `end_task {eos_timeout: 1..30}`, which holds the connection open for the tail and emits `eos` before closing. **That mechanism does not exist on this endpoint.**
- **Flush by feeding silence** *(live 2026-08-13)*. Stopping audio and waiting does NOT produce the last final: the closing utterance stayed a partial ("…that transcripts", losing "arrive correctly"), nothing more arrived for 10s, then the server closed with **1001**. Padding with digital silence made the endpointer fire and deliver the complete final **1.03s** later. The adapter therefore sends 1.5s of silence in `finish()` before closing. Silence is codec-specific: `0x00` for linear PCM, `0xFF` mulaw, `0xD5` alaw.

## Errors
- Upgrade-time HTTP: **401** invalid/missing key; **409** "session already active for identity". The SDK maps them to `AuthError` and `SessionError` off `exc.response.status_code` *(SDK)* — same handshake-status branch our adapter needs.
- **400** invalid query param (e.g. an unsupported `language` code), reason in the body. The adapter raises a non-recoverable `invalid_request` error with that text and `router/session.py` forwards it to the client verbatim; other provider errors stay masked.
- Docs say that after a successful upgrade the server sends no application-level error frames and just closes with a WS close frame. **The SDK contradicts this slightly**: unknown STT messages fall through to the shared parser, which knows `error {code, desc}` and `warning {code, message}` *(SDK)*. Treat the docs as the floor — parse an `error`/`warning` frame if one shows up, but do not depend on it; classify on the **close code** first.
- **No reconnection by design** *(SDK)*: a dropped connection ends iteration and the caller retries. Fits our failover model — the session layer owns the retry.

## Pricing (palabra.ai/pricing, 2026-08-13)
**$0.002 per minute of audio** for STT → `per_audio_minute_usd: 0.002`, `BillingBasis.AUDIO_TIME`. ($0.12/hr — same headline rate as Soniox realtime, but billed on audio rather than wall-clock, so idle silence is free here.) For reference the other lanes are S2S $0.04/min and TTS $0.03/1k chars; $50 signup credit.

## Open — blocks the adapter
1. **Does `409 session already active for identity` mean one concurrent stream per key?** Highest-impact unknown. If yes: `SPEECHROUTER_MAX_CONCURRENT_STREAMS` (def 20/key) oversubscribes; failover re-dialing while the old socket still closes collides with itself → 409 must be recoverable-with-backoff, not a hard fail; one house key can't serve multiple tenants.
2. Does the server flush a trailing final when the client stops sending, or must `finish()` grace-wait then close itself?
3. Idle timeout through silence. Partly answered: liveness is WS ping/pong, no app keepalive *(SDK)* — but how long a ping-healthy, audio-silent socket survives is still unknown.
4. Is `is_eos:true` a real VAD edge worth mapping to `utterance_end`?
5. Session/stream duration cap.
6. Source language codes — not mirrored in the adapter: the server owns the list and refuses unknown codes with 400 (see Errors), so `models.json` keeps `languages: ["auto"]`. Target codes for `translate_languages` still unconfirmed.
7. ~~Price and billing unit~~ — answered, see Pricing.
8. Faster-than-realtime ingest: the SDK paces because "the server requires it" and the wire carries `AUDIO_STREAM_TOO_FAST` *(SDK)* — so set `realtime_pacing_required=True` unless a burst test shows the server merely warns. Open question is warn-vs-drop, not whether pacing matters.

## Adapter notes
- URL-param config + close-code error classification → closest existing shape is **telnyx**, not soniox/gladia. Start from that adapter, but keep WS pings on (see Liveness) instead of Telnyx's `ping_interval=None`.
- Until (2) is answered, `finish()` grace-waits then closes the socket itself — otherwise a client waiting for `done` hangs to the session hard cap (the Telnyx failure mode). There is no server-side EOS to wait for.
- Pace inside `send_audio` at 320ms; do not forward client chunking verbatim. `send_audio` buffers into exact 320ms frames and meters them through a token bucket. The bucket is capped at 4× realtime rather than 1×, because a failover replays up to `ring_buffer_seconds` of audio into a fresh adapter and a strictly-realtime adapter could never work that backlog off; 2s of credit may bank during a quiet stretch. Nothing above the adapter re-chunks or paces — `Capabilities.chunk_ms_*` and `realtime_pacing_required` are declarative, the session engine never reads them.
- Mono only: the wire has no channel count and the server assumes mono, so `connect()` rejects `channels != 1` instead of returning garbage.
- `provider_params` may not restate `token`/`format`/`sample_rate`/`language` — `urlencode` would emit a second copy and let the server choose. Reserved keys are dropped with a warning.
- The key is a query param, so error text goes through `redact()` before it can reach a log (websockets' `InvalidURI` quotes the URL back).
- `keyterms=False`: no boosting param exists on this endpoint. Palabra does ship *hotword* glossaries, but they are a management REST API bound to the **S2S** pipeline *(SDK `management.py`)* — not reachable from these query params.
- Capabilities draft: `streaming`/`interim_results` True; `realtime_pacing_required` True; `word_timestamps`/`diarization`/`keyterms` False; encodings {linear16, linear32, mulaw, alaw}; chunk_ms ≈320; `languages={"auto"}` by design (6); `endpointing` pending (4); `billing_basis` pending (7).

- **Endpoint override.** `SPEECHROUTER_PALABRA_WS_BASE` (full stream URL, no query) wins over `SPEECHROUTER_PALABRA_REGION`; empty by default.
