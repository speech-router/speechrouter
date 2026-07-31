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

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → WebSocket query parameters; batch → query parameters. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `smart_format` | boolean | `false` | streaming · batch | Format numbers, dates, currency in the transcript |
| `punctuate` | boolean | `false` | streaming · batch | Add punctuation and capitalization |
| `endpointing` | integer | `10` | streaming | Silence (ms) before the endpointer fires |
| `utterance_end_ms` | integer | — | streaming | Gap (ms) that triggers UtteranceEnd; needs interim results on |
| `vad_events` | boolean | `false` | streaming | Emit speech-started events from the voice-activity detector |
| `diarize_model` | string | — | streaming · batch | Diarization model variant (replaces the deprecated diarize flag) |
| `multichannel` | boolean | `false` | streaming · batch | Transcribe each audio channel independently |
| `keywords` | string | — | streaming · batch | word:boost pairs — nova-2 family only (nova-3 uses keyterms) |
| `eot_threshold` | number | `0.7` | streaming | Flux models: end-of-turn confidence threshold |
| `eager_eot_threshold` | number | — | streaming | Flux models: earlier, lower-confidence end-of-turn signal |
| `eot_timeout_ms` | integer | `5000` | streaming | Flux models: force end-of-turn after this silence |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=deepgram/nova-3 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
