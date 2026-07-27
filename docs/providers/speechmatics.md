# Speechmatics — protocol brief (verified 2026-07-27)

## Realtime WS
- `wss://global.rt.speechmatics.com/v2/` (+ eu/us). Auth: handshake `Authorization: Bearer <KEY>`; browser: `?jwt=` temp key from `POST https://mp.speechmatics.com/v1/api_keys?type=rt` {ttl: 60–86400} (**type=rt required** — batch-type key won't open RT socket).
- **Send `StartRecognition` once, then WAIT for `RecognitionStarted` before ANY audio** (else protocol error).
- StartRecognition: `audio_format` {type: raw (encoding pcm_f32le|pcm_s16le|mulaw + sample_rate) | file (containers)}, `transcription_config`: language (req; `multi` for melia-1), **`model`: standard|enhanced|melia-1** (operating_point deprecated alias), `enable_partials` (**default FALSE**), `max_delay` (0.7–4s def 4), `max_delay_mode` (flexible|fixed), `diarization` (none|speaker|channel|channel_and_speaker), speaker_diarization_config {max_speakers, speaker_sensitivity, prefer_current_speaker}, `additional_vocab` [{content, sounds_like[]}] (≤1000), enable_entities (def true), punctuation_overrides, `conversation_config.end_of_utterance_silence_trigger` (0–2s; MUST be < max_delay), audio_filtering_config, transcript_filtering_config

## Protocol
- Client: StartRecognition, **AddAudio = raw binary frames** (server counts them), `EndOfStream` {last_seq_no: <YOUR count of binary frames — required, wrong count = protocol error>}, SetRecognitionConfig (mid-session: max_delay, enable_partials, conversation_config only), `ForceEndOfUtterance`, GetSpeakers
- Server: RecognitionStarted {id}, **AudioAdded {seq_no}** (ack per frame — THE backpressure signal: throttle on sent-vs-acked gap; no fixed buffer limit documented), AddPartialTranscript / AddTranscript, EndOfUtterance {metadata}, EndOfTranscript (flush complete — wait for it before closing or lose tail), Error {type, reason}, Warning, Info
- AddTranscript shape: {metadata:{start_time,end_time,transcript}, results:[{type: word|punctuation|entity, start_time, end_time, is_eos?, attaches_to?, alternatives:[{content, confidence, language, speaker ("S1"|"UU"), tags[]}], volume?}]}
- **AddTranscript = immutable finals; AddPartialTranscript covers span since last final, supersedes previous partial.** Timestamps: float SECONDS from stream start.
- Endpointing: end_of_utterance_silence_trigger → finals then EndOfUtterance msg; ForceEndOfUtterance for client-driven.

## Limits / errors
- Max session **48h**; killed after 1h no AddAudio, or **3 min no audio AND no WS pings — must send WS protocol pings during silence** (many libs don't auto-ping).
- Close codes: 1003 protocol_error, 1008 policy, 1011 internal, 4001 not_authorised, 4004 invalid_model, 4005 quota_exceeded, 4006 timelimit_exceeded. Error.types: invalid_message, invalid_config, not_authorised, quota_exceeded, idle_timeout, session_timeout... connection closes after any Error. Retry 5–10s only for quota_exceeded/job_error/internal_error.
- Concurrency: free 2, paid 50.

## Models
Engine Ursa 2. Tiers: standard (fast, default), enhanced (accuracy; medical), **melia-1** (June 2026: 56-lang code-switching, `language:"multi"`, BATCH-ONLY for now, no custom dict). ~50–80 langs, bilingual packs.

## Batch
`POST https://eu1.asr.api.speechmatics.com/v2/jobs` multipart (data_file + config JSON) or `fetch_data:{url}`. `GET /v2/jobs/{id}`, `/transcript?format=json-v2|txt|srt`. Webhooks: `notification_config` ARRAY (≤3): [{url, contents[], auth_headers[]}]. Same results grammar as RT (format 2.9 vs 2.1) — one parser serves both.

## Pricing (2026-07 — rate card no longer public)
Free 50h/mo. Pro from $0.129/hr (melia floor); 20% auto volume discount >500h/mo. Old per-model card (~$0.80–1.35/hr) likely stale — verify in portal before catalog pricing.
