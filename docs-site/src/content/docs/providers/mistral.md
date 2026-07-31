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

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → session.update fields (subset); batch → form fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `context_bias` | array | — | batch | Up to 100 bias terms (English-optimized) |
| `timestamp_granularities` | `word` · `segment` | — | batch | Timestamp detail level |
| `target_streaming_delay_ms` | integer | `800` | streaming | Latency target for realtime partials |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=mistral/voxtral-mini-latest \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
