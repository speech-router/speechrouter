---
title: OpenAI
description: Whisper and the GPT-4o transcribe family — LLM-grade accuracy.
sidebar: { order: 11 }
---

Whisper and the GPT-4o transcribe family — LLM-grade accuracy.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `openai/gpt-realtime-whisper` | streaming | $0.01698/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `openai/whisper-1` | batch | $0.006/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `openai/gpt-4o-transcribe` | streaming · batch | $0.006/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `openai/gpt-4o-mini-transcribe` | streaming · batch | $0.003/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `openai/gpt-4o-transcribe-diarize` | batch | $0.006/min | <span class="sr-yes">✓</span> | <span class="sr-no">—</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=openai/whisper-1 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
