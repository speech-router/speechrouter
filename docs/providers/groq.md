# Groq — protocol brief (verified 2026-07-27)

- `https://api.groq.com/openai/v1/audio/transcriptions` (+ /translations, English-out only) — **OpenAI-compatible wire shape**, batch only
- Models: `whisper-large-v3` ($0.111/hr, ~189x realtime), `whisper-large-v3-turbo` ($0.04/hr, ~216x). `distil-whisper-large-v3-en` SHUT DOWN 2025-08-23 → reject/alias to turbo.
- Limits: 25 MB free / 100 MB dev tier; min billed **10 seconds** per request; prompt ≤224 tokens
- response_format: json / verbose_json / text (**no srt/vtt** — gateway must synthesize srt/vtt from verbose_json words). Word+segment timestamps via timestamp_granularities with verbose_json. No diarization.
- **No realtime STT** (do not confuse with xAI Grok's wss STT). Realtime story = fast batch chunking.
