# Mistral (Voxtral) — protocol brief (verified 2026-07-27)

Feb 2026 refresh: "Voxtral Transcribe 2".

## Batch POST https://api.mistral.ai/v1/audio/transcriptions
- OpenAI-style multipart + extras: `file` OR **`file_url`** (remote URL!), `language`, `timestamp_granularities` (segment and/or word), **`diarize: true`**, **`context_bias`** (≤100 terms, English-optimized) — keyword boosting
- Model: `voxtral-mini-latest` → Voxtral Mini Transcribe V2. (voxtral-small = chat audio-in, NOT this endpoint)
- **Up to 3 HOURS of audio per request** (vs 25MB elsewhere). 13 languages. ~4% WER FLEURS claim.
- $0.003/min ($0.18/hr)
- Exact response JSON schema unverified — pull a live sample before finalizing adapter normalization.

## Realtime WS (new!)
- `wss://api.mistral.ai/v1/audio/transcriptions/realtime`, model `voxtral-mini-transcribe-realtime-2602`
- Audio: **pcm_s16le @ 16000 Hz** (vs OpenAI 24k — resampling needed between providers), ~480ms chunks
- Latency knob: `target_streaming_delay_ms` (240 fast .. 2400 max-accuracy)
- Events: session created → text deltas → done (+error). Raw JSON event names NOT published — verify against live socket or SDK source before adapter work.
- No diarization, no word timestamps in realtime. $0.006/min.
- Open weights: Voxtral-Mini-4B-Realtime-2602 on HF, Apache-2.0 → potential self-hosted fallback path.
