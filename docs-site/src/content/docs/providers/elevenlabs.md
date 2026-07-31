---
title: ElevenLabs
description: Scribe — high-accuracy STT from the voice company.
sidebar: { order: 7 }
---

Scribe — high-accuracy STT from the voice company.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `elevenlabs/scribe_v2_realtime` | streaming | $0.3888/hr | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `elevenlabs/scribe_v2` | batch | $0.21996/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `elevenlabs/scribe_v1` | batch | $0.21996/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=elevenlabs/scribe_v2 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
