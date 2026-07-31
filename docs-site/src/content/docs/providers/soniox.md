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

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → session config fields; batch → job fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `language_hints_strict` | boolean | `false` | streaming · batch | Restrict recognition to the hinted languages |
| `enable_language_identification` | boolean | `false` | streaming · batch | Tag tokens with the detected language |
| `max_endpoint_delay_ms` | integer | `2000` | streaming | Upper bound on endpoint latency |
| `endpoint_sensitivity` | number | — | streaming | Endpoint eagerness; docs suggest 0.3 for voice agents |
| `endpoint_latency_adjustment_level` | integer | — | streaming | Latency/accuracy trade for endpoint detection (2 = voice-agent preset) |
| `context` | object | — | streaming · batch | Domain context: general text, terms, translation_terms (≤8k tokens) |
| `translation` | object | — | streaming | Live translation config (one_way or two_way) |
| `client_reference_id` | string | — | streaming · batch | Your correlation id, echoed in Soniox logs |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=soniox/stt-async-v5 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
