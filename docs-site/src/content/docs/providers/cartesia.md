---
title: Cartesia
description: Ink — low-latency STT built for realtime agents.
sidebar: { order: 5 }
---

Ink — low-latency STT built for realtime agents.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `cartesia/ink-2` | streaming | $0.00648/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `cartesia/ink-whisper` | streaming · batch | $0.00216/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `cartesia/ink-2-turns` | streaming | $0.00648/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → WebSocket query parameters; batch → form fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `turn_start_threshold` | number | `0.8` | streaming | ink-2: confidence to open a turn |
| `turn_eager_end_threshold` | number | `0.4` | streaming | ink-2: early end-of-turn signal for LLM head-start |
| `turn_end_threshold` | number | `0.2` | streaming | ink-2: confidence to close a turn |
| `turn_end_timeout_ms` | integer | `5600` | streaming | ink-2: force turn end after this silence |
| `min_volume` | number | — | streaming | ink-whisper: ignore audio below this volume |
| `max_silence_duration_secs` | number | — | streaming | ink-whisper: silence tolerated before finalizing |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=cartesia/ink-whisper \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
