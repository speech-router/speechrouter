---
title: From OpenAI / Whisper
description: Same request shape, plus word timestamps, streaming, and 11 more vendors.
---

`POST /v1/audio/transcriptions` is OpenAI-compatible on purpose — for batch,
migration is a URL and a model prefix:

```diff
- https://api.openai.com/v1/audio/transcriptions
+ https://api.speechrouter.ai/v1/audio/transcriptions
-  -F model=whisper-1
+  -F model=openai/whisper-1
```

`response_format`, `language`, and `prompt` (via `provider_params`) behave as
you expect. Your OpenAI models are all here — `whisper-1`,
`gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe-diarize` —
at OpenAI's list prices.

## What you gain immediately

- **True streaming.** OpenAI realtime needs base64-in-JSON WebSocket framing
  and 24 kHz audio; SpeechRouter's `/v1/listen` takes binary PCM at your rate
  and resamples for OpenAI behind the scenes — or streams to any of the
  other providers with the same code.
- **Word timestamps beyond whisper-1.** `gpt-4o-transcribe` is json-only at
  OpenAI; on SpeechRouter, switching to a word-timing model
  (`assemblyai/universal-2`, `groq/whisper-large-v3`) is a slug edit.
- **`srt`/`vtt` everywhere** — including models where OpenAI doesn't offer
  them (the gateway synthesizes cues from word timings).
- **250 MB uploads** vs OpenAI's 25 MB.
- **Failover.** Whisper has bad days; your transcripts shouldn't.

## Whisper at Groq prices

The same `whisper-large-v3` weights run on Groq's hardware at ~200× realtime
for $0.111/hr ($0.04/hr turbo) — `model=groq/whisper-large-v3`. One slug, an
order of magnitude cheaper for batch.
