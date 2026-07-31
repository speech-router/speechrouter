---
title: AssemblyAI
description: Streaming turn model built for voice agents, plus strong async models.
sidebar: { order: 2 }
---

Streaming turn model built for voice agents, plus strong async models.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `assemblyai/universal-3-5-pro` | streaming | $0.45/session-hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `assemblyai/universal-streaming-english` | streaming | $0.15012/session-hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `assemblyai/universal-streaming-multilingual` | streaming | $0.15012/session-hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `assemblyai/universal-2` | batch | $0.20988/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

:::note[Session-time billing]
Models priced per **session-hour** meter wall-clock connection time — an open socket bills even while silent, exactly as the vendor bills us.
:::

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=assemblyai/universal-2 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
