# Soniox — protocol brief (verified 2026-07-27)

Docs: soniox.com/docs (append `.mdx` for raw markdown; index at /docs/llms.txt)

## Realtime WS
- Endpoint: `wss://stt-rt.soniox.com/transcribe-websocket`
- Auth: none on handshake; **first text frame = JSON config with `api_key` inline** (long-lived or temporary key)
- Models: **`stt-rt-v5`** (flagship, 2026-06-16), async `stt-async-v5`. v4 names auto-alias to v5; v3/preview retired. `endpoint_sensitivity` (-1..1) and `endpoint_latency_adjustment_level` (0..3) are v5-only.
- Config keys: `model`, `audio_format` ("auto" or raw e.g. `pcm_s16le` + `sample_rate` + `num_channels`), `language_hints[]`, `language_hints_strict`, `enable_speaker_diarization`, `enable_language_identification`, `enable_endpoint_detection`, `max_endpoint_delay_ms` (500-3000, default 2000), `context` {general kv / text / terms / translation_terms, ≤8k tokens}, `translation` (one_way/two_way), `client_reference_id`
- Audio: binary frames, OR text frames with base64. Raw formats: pcm_s8..s32/u8..u32 le|be, f32/f64 le|be, mulaw, alaw; "auto" containers: aac aiff amr asf flac mp3 ogg wav webm
- MUST send at realtime cadence — bursts → 408 "Input too slow"

## Response
JSON text frames: `{tokens: [...], final_audio_proc_ms, total_audio_proc_ms, finished?}`
Token: `text` (SUBWORD with embedded spacing — concatenate raw, never join with spaces), `start_ms`, `end_ms`, `confidence`, `is_final`, `speaker` (**string** "1"; up to 15), `language`, `translation_status` (none|original|translation), `source_language`
- **Finals sent exactly once → append. Non-finals wholesale-REPLACED each message.** transcript = finals + latest nonfinals
- Marker tokens INSIDE tokens[]: `<end>` (endpoint fired), `<fin>` (manual finalize ack) — both is_final, strip from text, use as events
- Translation tokens have NO timestamps
- Endpoint detection = semantic (pause + intonation + context). Voice-agent preset from docs: level 2, sensitivity 0.3, max_delay 1500
- Diarization accuracy degrades with endpointing/finalize — surface tradeoff

## Control (client→server text frames)
- `{"type":"finalize"}` — finalize all audio so far → tokens final + `<fin>` marker. Only after ~200ms silence; not more than every few seconds
- `{"type":"keepalive"}` — required every ≤20s without audio, else disconnect
- **End of audio = EMPTY frame** (binary or text "") → flush → `finished:true` message → server closes. NOT a JSON message.
- No mid-session reconfig.

## Errors / limits
- Error frame (final message, then immediate close): `{tokens:[], error_code: 503, error_type: "service_unavailable", error_message, more_info, request_id}` — branch on **error_type**: invalid_request, model_not_available, unauthenticated, organization_balance_exhausted, temp_api_key_session_expired, request_timeout, max_duration_reached (413, 300-min hard cap → reconnect), limit_exceeded, internal_error, service_unavailable (→ reconnect immediately, context lost)
- Idle >20s → close. Limits: 100 req/min, 10 concurrent (raisable)
- Temp keys: `POST https://api.soniox.com/v1/auth/temporary-api-key` {usage_type: "transcribe_websocket", expires_in_seconds, single_use?, max_session_duration_seconds?}

## Async
- `POST /v1/files` (multipart) → file_id; `POST /v1/transcriptions` {model, audio_url XOR file_id, ...same opts..., webhook_url + webhook_auth_header_name/value} → poll `GET /v1/transcriptions/{id}` → `GET .../transcript` {id, text, tokens[] (no is_final)}
- Webhook body: `{id, status: completed|error}` only — fetch transcript by id. Retries then permanent fail.
- Files/transcriptions NEVER auto-deleted (10GB/1000 files quota; 300-min max file). We must clean up.

## Pricing (2026-07-27)
- Realtime $0.12/hr, async $0.10/hr, translation free. **Billed on FULL STREAM WALL-CLOCK duration incl. keepalive idle** — gateway must close idle upstream sessions aggressively.

## Adapter notes (from scribemd prod + this brief)
- websockets.connect with ping_interval=None (Soniox handles liveness via its own keepalive)
- Monotonic end_ms dedup when mixing silence-promoted finals with late official finals
- speaker string→int for our schema
