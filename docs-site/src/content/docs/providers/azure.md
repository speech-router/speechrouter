---
title: Azure
description: Azure AI Speech — enterprise realtime + fast transcription.
sidebar: { order: 4 }
---

Azure AI Speech — enterprise realtime + fast transcription.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `azure/fast-transcription` | batch | $0.36/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `azure/speech-realtime` | streaming | $1/hr | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `azure/conversation-transcription` | streaming | $1.2/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded batch → fast-transcription definition fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

:::note
Realtime runs through the Azure Speech SDK — session knobs are gateway-managed, provider_params are not forwarded on streaming models.
:::

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `locales` | array | — | batch | Candidate locales for language identification |
| `diarization` | object | — | batch | {maxSpeakers: 2–35} — mono audio only |
| `channels` | array | — | batch | Channel indices to transcribe (≤2) |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=azure/fast-transcription \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
