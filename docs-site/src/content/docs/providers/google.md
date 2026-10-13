---
title: Google
description: Google Cloud Speech-to-Text (Chirp).
sidebar: { order: 10 }
---

Google Cloud Speech-to-Text (Chirp).

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `google/chirp_2` | streaming | $0.016/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `google/chirp_3` | streaming | $0.016/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `google/latest_long` | streaming | $0.016/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |

## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `google/chirp3-hd` | $30 per 1M chars | pcm, wav, mp3, opus, mulaw, alaw | 30+ |
| `google/neural2` | $16 per 1M chars | pcm, wav, mp3, opus, mulaw, alaw | 2+ |
| `google/studio` | $160 per 1M chars | pcm, wav, mp3, opus, mulaw, alaw | 2+ |
| `google/standard` | $4 per 1M chars | pcm, wav, mp3, opus, mulaw, alaw | 1+ |

## Provider options

:::note
Google streaming is gRPC with a typed config — provider_params are not forwarded. Standard SpeechRouter params cover language, diarization, and timestamps.
:::

## Try it

```text
wss://api.speechrouter.ai/v1/listen?model=google/chirp_2
```
Streaming-only — connect with the [SDKs](/sdks/javascript/) or see [Streaming](/guides/streaming/).

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
