---
title: Groq
description: Whisper on LPUs — the fastest batch Whisper anywhere.
sidebar: { order: 9 }
---

Whisper on LPUs — the fastest batch Whisper anywhere.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `groq/whisper-large-v3` | batch | $0.111/hr (min $0.00031/req) | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `groq/whisper-large-v3-turbo` | batch | $0.03996/hr (min $0.00011/req) | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=groq/whisper-large-v3 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
