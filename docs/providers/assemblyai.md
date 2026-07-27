# AssemblyAI — protocol brief (verified 2026-07-27)

## Realtime v3 WS (v2 RETIRED — close 410)
- `wss://streaming.assemblyai.com/v3/ws` (+ `.us.` / `.eu.` residency)
- Auth: `Authorization: <API_KEY>` — **NO Bearer prefix** (wrong format → 1008). Browser: `?token=` from `GET /v3/token?expires_in_seconds=60` (1–600s; tokens **single-use**).
- Models (`speech_model`): **`universal-3-5-pro`** (default flagship), `universal-streaming-english`, `universal-streaming-multilingual`
- Key params: `sample_rate` (8000–96000, def 16000; ignored for opus/aac), `encoding` (pcm_s16le|pcm_mulaw|opus|ogg_opus|aac ADTS-only), `mode` (max_accuracy|min_latency|balanced, U3.5-Pro), `format_turns`, `end_of_turn_confidence_threshold` (def 0.4), `min_turn_silence`/`max_turn_silence`, `vad_threshold`, `continuous_partials`, `include_partial_turns` (forced false w/ PII), **`speaker_labels`**+`max_speakers` (streaming diarization! +$0.12/hr, ~400ms extra latency), `language_codes`/`language_detection`, `domain=medical-v1`, `prompt`/`keyterms_prompt` (≤100)/`agent_context`, `redact_pii`, `session_heartbeat`, `inactivity_timeout` (5–3600s)

## HARD CONSTRAINT: chunks 50–1000ms AND real-time pacing enforced
Close 3007 on violation ("audio sent faster than real-time"). **Gateway CANNOT burst file audio to this provider** — must re-pace. Capability flag: realtime_pacing_required.

## Server messages
- `Begin` {id, expires_at (unix s), configuration}
- `SpeechStarted` {timestamp, confidence} (U3.5-Pro; guarantees ≥1 Turn follows)
- `Turn` {turn_order, turn_is_formatted, end_of_turn, transcript, end_of_turn_confidence, utterance, words:[{start,end,text,confidence,word_is_final, speaker?}], language_code?, speaker_label?}
- `Heartbeat` (5s, opt-in), `SpeakerRevision` {revisions[]} (**retroactive speaker relabel before Termination**), `Termination` {audio_duration_seconds, session_duration_seconds}, `Error` {error_code, error}
- **Semantics differ by model behind one protocol**: universal-streaming-* = IMMUTABLE accumulate-only; U3.5-Pro = true partials (`word_is_final:false` mutable), each Turn message SUPERSEDES previous within turn — key off `word_is_final`, never model name.
- `format_turns=true` (US models) → TWO end_of_turn:true messages same turn_order (unformatted then formatted) — dedupe. `end_of_turn:true` is the ONLY reliable turn-completion signal.
- Timestamps: **ms from audio-stream start**.

## Client control
`{"type":"ForceEndpoint"}`, `{"type":"Terminate"}` (flush → Termination → close), `{"type":"KeepAlive"}` (resets inactivity_timeout), `{"type":"UpdateConfiguration", ...}` (silence thresholds/vad/mode/prompts/language_codes — NOT sample_rate/encoding/model)

## Limits / close codes
- Max session 3h (3008); **auto-bills full duration if never closed** → leaked connection = 3h bill. BILLING IS SESSION-TIME not audio-time.
- 1008 auth; 1011 internal (retry); 3005 unknown; 3006 bad msg/inactivity; 3007 pacing/chunk; 3008 expired; 3009 concurrency (5/min free, 100/min paid)

## Batch v2
1. `POST /v2/upload` (raw bytes) → upload_url; 2. `POST /v2/transcript` {audio_url, speaker_labels, language_detection, speech_model: universal|slam-1, webhook_url+webhook_auth_token}; 3. poll `GET /v2/transcript/{id}` or webhook. Response: text, words[{text,start,end,confidence,speaker}] (ms), utterances[].

## Pricing (2026-07)
Streaming: U3.5-Pro $0.45/hr, US-English/multi $0.15/hr — **billed on WS-open duration**. Batch: U3.5-Pro $0.21/hr, Universal-2 $0.15/hr. Add-ons stack (diarization, medical, entities). Free $50.
