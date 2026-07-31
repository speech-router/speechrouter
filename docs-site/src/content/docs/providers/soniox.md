---
title: Soniox
description: 60+ languages with translation-grade accuracy; realtime bills wall-clock session time.
sidebar: { order: 1 }
---

60+ languages with translation-grade accuracy; realtime bills wall-clock session time.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `soniox/stt-rt-v5` | streaming | $0.12/session-hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `soniox/stt-async-v5` | batch | $0.1/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

:::note[Session-time billing]
Models priced per **session-hour** meter wall-clock connection time — an open socket bills even while silent, exactly as the vendor bills us.
:::

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=soniox/stt-async-v5 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
