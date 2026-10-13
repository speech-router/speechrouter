---
title: Gemini
description: Gemini 3.5 Transcribe Live at $0.30/hr — 85+ languages, custom vocabulary, and a SMART mode that cleans up disfluencies as it goes.
sidebar: { order: 8 }
---

Gemini 3.5 Transcribe Live at $0.30/hr — 85+ languages, custom vocabulary, and a SMART mode that cleans up disfluencies as it goes.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `gemini/gemini-3.5-transcribe-live` | streaming | $0.3/hr | <span class="sr-no">—</span> | <span class="sr-no">—</span> |

## Text-to-speech

Token prices are per 1M tokens. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `gemini/gemini-3.8-flash-tts` | $0.5 text in · $9 audio out (from 2027-01-01: $1 text in · $18 audio out) | pcm, wav, mulaw, alaw | 30 |
| `gemini/gemini-3.8-flash-lite-tts` | $0.5 text in · $6 audio out (from 2027-01-01: $1 text in · $12 audio out) | pcm, wav, mulaw, alaw | 30 |

## Live voice

Speech-to-speech sessions in the vendor's own protocol (`gemini-live`). Prices
per 1M tokens. [Live voice guide](/guides/live/).

| Model | List price |
| --- | --- |
| `gemini/gemini-3.8-live` | $0.75 text in · $3 audio in · $1 image in · $4.5 text out · $12 audio out |
| `gemini/gemini-3.8-live-extended-thinking` | $0.75 text in · $3 audio in · $1 image in · $4.5 text out · $12 audio out |
| `gemini/gemini-2.5-flash-native-audio-preview-12-2025` (deprecated) | $0.5 text in · $3 audio in · $3 image in · $2 text out · $12 audio out |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → the Live API `setup` message. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

:::note
Keys are the Live API's own camelCase field names. `mode`, `languageCodes` and `customVocabulary` are merged into setup.inputAudioTranscription; anything else lands at the top level of `setup` (realtimeInputConfig, contextWindowCompression, ...). `model` and `sessionResumption` are owned by the adapter — it reconnects on its own around the ~10-minute connection cap — and are dropped with a warning. The unified `language` sets languageCodes and `keyterms` sets customVocabulary; restating them here overrides that.
:::

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `mode` | `VERBATIM` · `SMART` | `"VERBATIM"` | streaming | VERBATIM keeps fillers, repetitions and false starts; SMART removes disfluencies and applies punctuation, grammar and casing |
| `languageCodes` | array | — | streaming | BCP-47 codes to constrain recognition; empty (the default) means automatic detection. Use this instead of `language` to allow several languages |
| `customVocabulary` | array | — | streaming | Up to 1000 phrases biasing recognition toward domain terms; Google recommends staying near 100. Same field the unified `keyterms` sets |
| `realtimeInputConfig` | object | — | streaming | Voice-activity tuning, e.g. {"automaticActivityDetection": {"silenceDurationMs": 500, "prefixPaddingMs": 100}}; set automaticActivityDetection.disabled to drive turns yourself |

## Try it

```text
wss://api.speechrouter.ai/v1/listen?model=gemini/gemini-3.5-transcribe-live
```
Streaming-only — connect with the [SDKs](/sdks/javascript/) or see [Streaming](/guides/streaming/).

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
