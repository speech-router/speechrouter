# Google Cloud STT v2 — protocol brief (verified 2026-07-27)

## Streaming = gRPC ONLY (no WS, no REST streaming — triple-confirmed)
- Client: `google-cloud-speech` → `speech_v2.SpeechAsyncClient.streaming_recognize(async iterator)` — natural asyncio fit. Auth = ADC/service account (not API key headers).
- First request: `recognizer` (implicit `projects/{p}/locations/{loc}/recognizers/_` fully supported — never create one) + streaming_config; then audio-only messages (oneof — never both).
- Config: `auto_decoding_config {}` (auto-detects WAV etc.) vs `explicit_decoding_config {encoding, sample_rate_hertz, audio_channel_count}`; `model`, `language_codes[]`, `features {enable_word_time_offsets, enable_word_confidence, diarization_config {min/max_speaker_count — both required}}`, `streaming_features {interim_results, enable_voice_activity_events, voice_activity_timeout}`
- **Endpoint must match recognizer location**: us-speech.googleapis.com / eu-speech.googleapis.com REQUIRED for chirp_3 (multi-region), {location}-speech.googleapis.com for chirp_2 (us-central1, europe-west4, asia-southeast1). ClientOptions(api_endpoint=...).

## Models (2026-07)
- **chirp_3**: streaming GA, **NO word timestamps in streaming** (utterance-level only), **NO streaming diarization**, auto language detect, built-in denoiser.
- **chirp_2**: word timestamps YES, diarization NO, ~18 streaming langs, +translation_config.
- **telephony** (8k) / latest_long / latest_short (END_OF_SINGLE_UTTERANCE): word timestamps yes.
- Rule: streaming word timing → chirp_2/telephony/latest_*, NOT chirp_3.

## Response
StreamingRecognizeResponse {results[{alternatives[{transcript, confidence, words[]}], is_final, stability, result_end_offset, channel_tag, language_code}], speech_event_type (SPEECH_ACTIVITY_BEGIN/END, END_OF_SINGLE_UTTERANCE), speech_event_offset, metadata{total_billed_duration}}
- WordInfo: {word, **start_offset/end_offset** (v2 renamed from start_time!), confidence, speaker_label} — protobuf Durations ("1.500s" in JSON).
- Diarized results = running aggregate (each result repeats prior words) — dedupe.
- VAD timeouts: >500ms <60s; **measured by AUDIO BYTES SENT, not wall clock** (critical for proxy pacing); timeout → server closes stream.

## HARD LIMITS (gateway-critical)
- **Stream open MAX 5 MINUTES → gateway must proactively rotate streams and bridge transcripts** (like failover but scheduled)
- **25 KB audio per stream message**
- 300 concurrent streams/region; 3000 stream-req/min/region

## Batch
BatchRecognize: **GCS input only**, ≤5 files/request, ≤8h/file; inline or GCS output; long-running Operation; DYNAMIC_BATCHING = cheaper/slower ($0.003/min).

## Pricing
v2 tiered: $0.016/min (0–500k min/mo) → $0.010 → $0.008 → $0.004 (2M+). Per-second rounding to 1s. **Each channel billed separately. No free tier in v2.**
