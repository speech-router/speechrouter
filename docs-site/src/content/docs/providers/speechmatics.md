---
title: Speechmatics
description: Broad language coverage; Melia-1 code-switches across 56 languages.
sidebar: { order: 12 }
---

Broad language coverage; Melia-1 code-switches across 56 languages.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `speechmatics/enhanced` | streaming · batch | $1.04/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `speechmatics/standard` | streaming · batch | $0.7992/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `speechmatics/melia-1` | batch | $0.129/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → transcription_config fields; batch → transcription_config fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `max_delay` | number | `4` | streaming | Max seconds before a final is emitted |
| `max_delay_mode` | `flexible` · `fixed` | — | streaming | Whether max_delay may stretch to finish entities |
| `speaker_diarization_config` | object | — | streaming · batch | {max_speakers, speaker_sensitivity, prefer_current_speaker} |
| `additional_vocab` | array | — | streaming · batch | [{content, sounds_like[]}] — up to 1000 entries with pronunciations |
| `enable_entities` | boolean | `true` | streaming · batch | Emit typed entities (numbers, dates) in results |
| `punctuation_overrides` | object | — | streaming · batch | Tune permitted marks and sensitivity |
| `conversation_config` | object | — | streaming | {end_of_utterance_silence_trigger: 0–2s} — must be < max_delay |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=speechmatics/enhanced \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
