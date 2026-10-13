---
title: Fish Audio
description: Fish Audio S2 — huge community voice library; billed per UTF-8 byte.
sidebar: { order: 8 }
---

Fish Audio S2 — huge community voice library; billed per UTF-8 byte.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `fishaudio/s2.1-pro` | $15 per 1M UTF-8 bytes | pcm, wav, mp3, opus, mulaw, alaw | 1+ |
| `fishaudio/s2-pro` | $15 per 1M UTF-8 bytes | pcm, wav, mp3, opus, mulaw, alaw | 1+ |
| `fishaudio/s1` | $15 per 1M UTF-8 bytes | pcm, wav, mp3, opus, mulaw, alaw | 1+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "fishaudio/s2.1-pro", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
