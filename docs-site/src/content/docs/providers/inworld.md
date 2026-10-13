---
title: Inworld
description: Inworld TTS-2 — expressive voices at $15–25 per 1M characters.
sidebar: { order: 12 }
---

Inworld TTS-2 — expressive voices at $15–25 per 1M characters.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `inworld/inworld-tts-2` | $25 per 1M chars | pcm, wav, mp3, opus, flac, mulaw, alaw | 3+ |
| `inworld/inworld-tts-2-flash` | $15 per 1M chars | pcm, wav, mp3, opus, flac, mulaw, alaw | 3+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "inworld/inworld-tts-2", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
