# SpeechRouter Spec — v0

Source of truth for the entire product. The gateway's pydantic models and the
TS/Python SDK types are code-generated from these files; CI fails on drift.

| File | Defines |
|---|---|
| `events.schema.json` | WebSocket protocol: every event on `/v1/listen` and `/v1/speak` |
| `catalog.schema.json` | Model catalog entries: capabilities, pricing, latency |
| `openapi.yaml` | REST endpoints (OpenAI-compatible) — TODO |

## Protocol decisions (settled 2026-07-27)

1. **Audio framing — raw binary WS frames.** Audio is always a binary frame
   (client→server on `/v1/listen`, server→client on `/v1/speak`); every JSON
   event is a text frame. No base64: it costs ~33% bandwidth + CPU on a
   continuous stream (the most-criticized part of OpenAI Realtime), binary is
   what Deepgram/Soniox/AssemblyAI already do, and Deepgram-compat mode
   requires it.

2. **Time base — audio-time seconds from the session's first audio sample.**
   Not wall clock, not provider-native. Monotonic across failover: the new
   provider's clock restarts at zero, adapters apply the session offset so the
   timeline is seamless. Clients never do clock math.

3. **Speaker labels across failover — epoch-scoped, upgradeable.**
   `provider_switched.speaker_mapping_preserved` is required. v1 always emits
   `false` (labels reset; client is told explicitly). Because the ring-buffer
   replay makes the new provider re-label audio the old provider already
   labeled, the gateway can later align old↔new speakers from the overlap and
   emit `true` — a pure upgrade, never a breaking change.

4. **Failover dedup is a gateway guarantee.** Replayed ring-buffer audio means
   the new provider re-transcribes ranges already delivered; the gateway
   suppresses re-covered *finals* so clients never dedup. If clients had to,
   every SDK would reimplement it badly.

5. **TTS input — JSON `text.delta` in, binary audio out, `clear`/`cleared`
   for barge-in.** Text is small so JSON framing is free; audio stays binary
   (decision 1). `clear` discards queued synthesis; the `cleared` ack carries
   `last_seq` so clients know which in-flight chunks are stale. Voice-agent
   interruption is first-class, not an afterthought.

6. **`keepalive` client event.** Browsers cannot send WS protocol pings, so
   silence (muted mic, no text) would idle-timeout sessions. Same reason
   Deepgram has JSON KeepAlive.

7. **Error codes — closed enum of 16**, grouped auth / billing / limits /
   request / runtime / server, each with `recoverable`. REST wraps the same
   codes in an OpenAI-compatible `{error:{code,message,type}}` envelope.
   Codes are forever; additions allowed, renames never.

## Batch modes (decided 2026-07-27)

`POST /v1/audio/transcriptions` supports three ways to get a result:

- **Sync (default):** request → transcript in the response. For files where
  holding the connection is fine.
- **Async:** pass `callback_url` (and/or `async=true`) → `202 {job_id}`;
  result POSTed to the callback (HMAC-signed) and retrievable via
  `GET /v1/audio/transcriptions/{job_id}`. For hour-long files and queue
  workflows — no client babysitting an open connection.
- **File over WebSocket:** clients can push a whole audio file through
  `WSS /v1/listen` faster than realtime and collect events until `done`.
  Falls out of the protocol for free; useful when you want word-by-word
  progress on a batch file. Documented, not a separate API.

## Still open (non-blocking)

- `openapi.yaml` for the three REST endpoints (incl. the job resource above) —
  write when scaffolding the gateway API layer.
- Deepgram-compat mode mapping table (their event names ↔ ours) — write with
  the compat layer, not before.
