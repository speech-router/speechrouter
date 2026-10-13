---
title: Rime
description: Rime TTS — Coda and Mist v3 voices built for conversational agents.
sidebar: { order: 19 }
---

Rime TTS — Coda and Mist v3 voices built for conversational agents.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `rime/coda` | $50 per 1M chars | pcm, wav, mp3, opus, mulaw, alaw | 15+ |
| `rime/mistv3` | $30 per 1M chars | pcm, wav, mp3, opus, mulaw, alaw | 15+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "rime/coda", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
