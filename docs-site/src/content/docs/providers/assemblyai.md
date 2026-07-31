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

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → WebSocket query parameters; batch → job fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `end_of_turn_confidence_threshold` | number | `0.4` | streaming | Confidence needed to declare end of turn |
| `min_turn_silence` | integer | — | streaming | Minimum silence (ms) before a turn can end |
| `max_turn_silence` | integer | — | streaming | Silence (ms) that forces end of turn |
| `vad_threshold` | number | — | streaming | Voice-activity detection sensitivity |
| `continuous_partials` | boolean | `false` | streaming | Emit partials continuously instead of on change |
| `max_speakers` | integer | — | streaming | Cap for streaming diarization |
| `language_detection` | boolean | `false` | streaming · batch | Auto-detect the spoken language |
| `domain` | `medical-v1` | — | streaming | Domain-tuned recognition |
| `prompt` | string | — | streaming | Free-text context to bias recognition |
| `redact_pii` | boolean | `false` | streaming · batch | Redact personally identifiable information |
| `inactivity_timeout` | integer | — | streaming | Close the vendor session after this many silent seconds |
| `mode` | `max_accuracy` · `balanced` · `min_latency` | — | streaming | universal-3-5-pro: latency/accuracy preset |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=assemblyai/universal-2 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
