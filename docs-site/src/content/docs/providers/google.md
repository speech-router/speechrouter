---
title: Google
description: Google Cloud Speech-to-Text (Chirp).
sidebar: { order: 8 }
---

Google Cloud Speech-to-Text (Chirp).

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `google/chirp_2` | streaming | $0.016/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `google/chirp_3` | streaming | $0.016/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `google/latest_long` | streaming | $0.016/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |

## Try it

```text
wss://api.speechrouter.ai/v1/listen?model=google/chirp_2
```
Streaming-only — connect with the [SDKs](/sdks/javascript/) or see [Streaming](/guides/streaming/).

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
