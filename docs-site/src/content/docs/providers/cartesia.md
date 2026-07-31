---
title: Cartesia
description: Ink — low-latency STT built for realtime agents.
sidebar: { order: 5 }
---

Ink — low-latency STT built for realtime agents.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `cartesia/ink-2` | streaming | $0.00648/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `cartesia/ink-whisper` | streaming · batch | $0.00216/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `cartesia/ink-2-turns` | streaming | $0.00648/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=cartesia/ink-whisper \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
