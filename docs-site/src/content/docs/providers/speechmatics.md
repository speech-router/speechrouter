---
title: Speechmatics
description: Broad language coverage; Melia-1 code-switches across 56 languages.
sidebar: { order: 12 }
---

Broad language coverage; Melia-1 code-switches across 56 languages.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `speechmatics/enhanced` | streaming · batch | $1.04/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `speechmatics/standard` | streaming · batch | $0.7992/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `speechmatics/melia-1` | batch | $0.129/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=speechmatics/enhanced \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
