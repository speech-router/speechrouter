---
title: MiniMax
description: MiniMax Speech 2.x — HD and Turbo voices, strong multilingual coverage.
sidebar: { order: 14 }
---

MiniMax Speech 2.x — HD and Turbo voices, strong multilingual coverage.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.


## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `minimax/speech-2.8-hd` | $100 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 15+ |
| `minimax/speech-2.8-turbo` | $60 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 15+ |
| `minimax/speech-2.6-hd` | $100 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 15+ |
| `minimax/speech-2.6-turbo` | $60 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 15+ |
| `minimax/speech-02-hd` | $100 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 15+ |
| `minimax/speech-02-turbo` | $60 per 1M chars | pcm, wav, mp3, flac, opus, mulaw, alaw | 15+ |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "minimax/speech-2.8-hd", "input": "Hello from SpeechRouter", "response_format": "wav"}' \
  --output hello.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
