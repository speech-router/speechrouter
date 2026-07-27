# ElevenLabs — STT protocol brief (verified 2026-07-27)

## Realtime — Scribe v2 Realtime (~150ms, 90+ langs)
- `wss://api.elevenlabs.io/v1/speech-to-text/realtime` (+ regional us/eu/in/sg residency hosts)
- Auth: `xi-api-key` header; browser: `?token=` single-use token (15-min expiry)
- Params: model_id=`scribe_v2_realtime`, audio_format (pcm_8000..pcm_48000, def pcm_16000; ulaw_8000), language_code, secondary_languages[], **commit_strategy: manual|vad**, vad_threshold, vad_silence_threshold_secs, min_speech/silence_duration_ms, include_timestamps, include_language_detection, keyterms[] (≤50×20ch), no_verbatim, filter_background_audio, enable_logging=false (zero-retention)
- **AUDIO IS BASE64 IN JSON** (not binary): `{"message_type":"input_audio_chunk","audio_base_64":"...","commit":false,"sample_rate":16000,"previous_text"?}` — manual commit = `"commit":true` on a chunk; vad mode auto-commits on silence
- Server (`message_type`): `session_started` {session_id, config}, `partial_transcript` {text}, `committed_transcript` {text}, `committed_transcript_with_timestamps` (+language_code, words:[{text,start,end,**type: word|spacing|audio_event**,speaker_id,logprob,characters[],channel_index}]), `committed_transcript_entities`, error types: error, auth_error, quota_exceeded, **commit_throttled**, rate_limited, queue_overflow, resource_exhausted, session_time_limit_exceeded, input_error, chunk_size_exceeded, insufficient_audio_activity, transcriber_error

## Batch — POST /v1/speech-to-text
- model_id: `scribe_v2` | `scribe_v1`; file ≤5GB or cloud_storage_url; `diarize` (+num_speakers ≤32), timestamps_granularity (none|word|character), tag_audio_events, use_multi_channel (≤5) + multichannel_output_style, keyterms (≤1000), entity_detection/redaction (65 types), detect_speaker_roles, `webhook` (async)
- Response: {language_code, language_probability, text, words:[{text, type, start, end, speaker_id, logprob, characters, channel_index}]}

## Pricing
Batch ~$0.22/hr; realtime ~$0.39/hr; +entity $0.07/hr, +keyterms $0.05/hr.
