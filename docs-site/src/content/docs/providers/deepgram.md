---
title: Deepgram
description: The realtime workhorse — fast, cheap, excellent English.
sidebar: { order: 6 }
---

The realtime workhorse — fast, cheap, excellent English.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `deepgram/nova-3` | streaming · batch | $0.0048/min | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `deepgram/nova-3-medical` | streaming · batch | $0.0048/min | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `deepgram/nova-2` | streaming · batch | $0.0048/min | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `deepgram/flux-general-en` | streaming | $0.00648/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `deepgram/flux-general-multi` | streaming | $0.0078/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=deepgram/nova-3 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
