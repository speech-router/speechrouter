---
title: ElevenLabs
description: Scribe — high-accuracy STT from the voice company.
sidebar: { order: 7 }
---

Scribe — high-accuracy STT from the voice company.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `elevenlabs/scribe_v2_realtime` | streaming | $0.3888/hr | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `elevenlabs/scribe_v2` | batch | $0.21996/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `elevenlabs/scribe_v1` | batch | $0.21996/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → session fields; batch → form fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `commit_strategy` | `manual` · `vad` | — | streaming | When transcripts commit: on silence (vad) or on demand |
| `vad_threshold` | number | — | streaming | Voice-activity sensitivity for vad commits |
| `vad_silence_threshold_secs` | number | — | streaming | Silence that triggers a vad commit |
| `secondary_languages` | array | — | streaming | Additional expected languages |
| `no_verbatim` | boolean | `false` | streaming | Clean up disfluencies |
| `filter_background_audio` | boolean | `false` | streaming | Suppress non-speech audio |
| `enable_logging` | boolean | `true` | streaming | false = zero-retention mode at ElevenLabs |
| `num_speakers` | integer | — | batch | Expected speaker count for diarization |
| `timestamps_granularity` | `none` · `word` · `character` | — | batch | Timestamp detail level |
| `tag_audio_events` | boolean | `false` | batch | Mark laughter, applause, and other audio events |
| `entity_detection` | boolean | `false` | batch | Detect 65 entity types (extra vendor charge) |
| `detect_speaker_roles` | boolean | `false` | batch | Label agent/customer roles |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=elevenlabs/scribe_v2 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
