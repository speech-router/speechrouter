---
title: Meta
description: Muse Voice Transcribe — 25 languages with code-switching, turn detection and speaker labels at $0.18/hr.
sidebar: { order: 13 }
---

Muse Voice Transcribe — 25 languages with code-switching, turn detection and speaker labels at $0.18/hr.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `meta/muse-voice-transcribe-1.0` | streaming · batch | $0.18/hr | <span class="sr-yes">✓</span> | <span class="sr-no">—</span> |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → handshake JSON frame; batch → `request` JSON part. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

:::note
Audio must be linear16 mono at 16 kHz or 24 kHz (streaming) or a mono 16-bit PCM WAV at one of those rates (batch, max 32 MB / 10 min); nothing is transcoded. `diarization=true` selects DIARIZATION mode and overrides `mode`. The unified `language` hint is translated to a language name and merged into `languageBias`; `keyterms` are merged into `keywords`. `authorization`, `audioEncoding`, `model`, `partialMode` and `emitAudioProgress` are owned by the adapter and ignored here.
:::

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `mode` | `ENDPOINTING` · `PUSH_TO_TALK` · `DIARIZATION` | `"ENDPOINTING"` | streaming · batch | Turn detection. ENDPOINTING emits one final per detected utterance; PUSH_TO_TALK emits a single final when input ends (no turn timestamps); DIARIZATION adds speaker labels |
| `languageBias` | array | — | streaming · batch | Language names to steer recognition toward, e.g. ["English", "French"]; merged with `language` |
| `keywords` | array | — | streaming · batch | Vocabulary to bias toward (names, jargon, product terms); merged with `keyterms` |
| `zdrOverride` | boolean | — | streaming | Override the account's Zero Data Retention policy for this session: true forces metadata-only logging |
| `sessionId` | string | — | streaming · batch | Correlation id echoed in Meta's server logs; generated upstream when omitted |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=meta/muse-voice-transcribe-1.0 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
