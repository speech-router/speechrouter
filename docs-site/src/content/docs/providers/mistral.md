---
title: Mistral
description: Voxtral — open-weights transcription via Mistral's API.
sidebar: { order: 10 }
---

Voxtral — open-weights transcription via Mistral's API.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `mistral/voxtral-mini-latest` | batch | $0.003/min | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `mistral/voxtral-mini-transcribe-realtime-2602` | streaming | $0.006/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=mistral/voxtral-mini-latest \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
