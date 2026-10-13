---
title: Smallest.ai
description: Smallest.ai Lightning v3.1 — 217 voices, native 8 kHz mu-law, $17.50 per 1M characters.
sidebar: { order: 20 }
---

Smallest.ai Lightning v3.1 — 217 voices, native 8 kHz mu-law, $17.50 per 1M characters.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `smallest/lightning_v3.1` | $17.5 per 1M chars | pcm, wav, mp3, mulaw, alaw | 7+ |
| `smallest/lightning_v3.1_pro` | $19.5 per 1M chars | pcm, wav, mp3, mulaw, alaw | 11+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "smallest/lightning_v3.1", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
