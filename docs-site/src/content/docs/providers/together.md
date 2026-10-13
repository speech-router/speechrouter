---
title: Together AI
description: Kokoro-82M on Together AI — the $4 per 1M characters open-weight tier (non-PHI traffic only).
sidebar: { order: 23 }
---

Kokoro-82M on Together AI — the $4 per 1M characters open-weight tier (non-PHI traffic only).

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `together/kokoro-82m` | $4 per 1M chars | pcm, wav, mulaw, alaw | 7+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "together/kokoro-82m", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
