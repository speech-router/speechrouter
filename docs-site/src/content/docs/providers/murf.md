---
title: Murf
description: Murf Falcon 2 — low-latency streaming TTS at $10 per 1M characters.
sidebar: { order: 16 }
---

Murf Falcon 2 — low-latency streaming TTS at $10 per 1M characters.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `murf/falcon-2` | $10 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 9+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "murf/falcon-2", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
