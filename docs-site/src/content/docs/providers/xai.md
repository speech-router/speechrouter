---
title: xAI
description: Grok Voice Transcribe 2.0 — word timings, speaker labels and keyterms included; $0.20/hr streaming, $0.10/hr batch.
sidebar: { order: 17 }
---

Grok Voice Transcribe 2.0 — word timings, speaker labels and keyterms included; $0.20/hr streaming, $0.10/hr batch.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `xai/grok-voice-transcribe-2.0` | streaming | $0.2/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |
| `xai/grok-voice-transcribe-2.0-batch` | batch | $0.1/hr | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → WebSocket query params; batch → multipart form fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

:::note
`language` is sent as a bare code (`en-US` → `en`) and only switches on inverse text normalization (numbers, currency, dates) — the model auto-detects the spoken language either way; batch adds `format=true` alongside it. Filler words (uh, um) are removed unless `filler_words` is true. `model`, `encoding`, `sample_rate`, `channels` and `multichannel` are owned by the adapter on streaming. Streaming and batch are separate slugs because xAI prices them differently ($0.20/hr vs $0.10/hr).
:::

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `endpointing` | integer | `400` | streaming | Silence (ms, 0–5000) before an utterance final; 0 fires on any VAD silence boundary |
| `smart_turn` | number | — | streaming | End-of-turn model threshold (0–1, e.g. 0.7); pauses below it stay mid-utterance |
| `smart_turn_timeout` | integer | — | streaming | Max silence (ms, 1–5000) before an utterance final is forced when smart_turn is on |
| `filler_words` | boolean | `false` | streaming · batch | Keep filler words (uh, um, er) in text and words |
| `vad_threshold` | number | — | streaming · batch | Speech-probability gate (0–1; default 0.08 streaming, 0.5 batch); lower keeps quiet or telephony speech, 0 disables |
| `format` | boolean | — | batch | Inverse text normalization; requires `language` (sent automatically with it) |
| `multichannel` | boolean | — | batch | Transcribe each channel independently; words are merged in time order |
| `audio_format` | `pcm` · `mulaw` · `alaw` | — | batch | Only for headerless raw audio (with `sample_rate`); containers are auto-detected |
| `sample_rate` | integer | — | batch | Raw audio only: 8000, 16000, 22050, 24000, 44100 or 48000 |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=xai/grok-voice-transcribe-2.0-batch \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
