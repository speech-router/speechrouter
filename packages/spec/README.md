# SpeechRouter Spec — v0 DRAFT

Source of truth for the entire product. The gateway's pydantic models and the
TS/Python SDK types are code-generated from these files; CI fails on drift.

| File | Defines |
|---|---|
| `events.schema.json` | WebSocket protocol: every event on `/v1/listen` and `/v1/speak` |
| `catalog.schema.json` | Model catalog entries: capabilities, pricing, latency |
| `openapi.yaml` | REST endpoints (OpenAI-compatible) — TODO |

## Open questions to settle before writing gateway code

1. **Binary framing on `/v1/listen`**: raw binary WS frames for audio in (like
   Deepgram) vs base64-in-JSON (like OpenAI Realtime). Draft assumes raw binary
   frames in, JSON text frames out. Deepgram-compat mode requires binary anyway.
2. **`Transcript.words` timestamps**: seconds from session start (draft) vs
   provider-native epochs. Normalizing to session-relative is more work in
   adapters but the only sane client experience — confirm.
3. **Speaker labels across failover**: after `provider_switched`, speaker
   indices from the new provider won't match the old ones. Options: reset +
   document it (draft), or gateway-side speaker re-mapping (hard, later).
4. **TTS input**: text chunks over WS as `{type:"text.delta"}` events —
   not yet in schema, add before implementing `/v1/speak`.
5. **Error codes**: is the draft list (`auth_failed | insufficient_credits |
   provider_error | unsupported_capability | rate_limited`) complete enough
   for v0? Codes are forever once published.
