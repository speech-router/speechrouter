---
title: OpenAI
description: Whisper and the GPT-4o transcribe family — LLM-grade accuracy.
sidebar: { order: 17 }
---

Whisper and the GPT-4o transcribe family — LLM-grade accuracy.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `openai/gpt-realtime-whisper` | streaming | $0.01698/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `openai/whisper-1` | batch | $0.006/min | <span class="sr-no">—</span> | <span class="sr-yes">✓</span> |
| `openai/gpt-4o-transcribe` | streaming · batch | $0.006/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `openai/gpt-4o-mini-transcribe` | streaming · batch | $0.003/min | <span class="sr-no">—</span> | <span class="sr-no">—</span> |
| `openai/gpt-4o-transcribe-diarize` | batch | $0.006/min | <span class="sr-yes">✓</span> | <span class="sr-no">—</span> |

## Text-to-speech

Token prices are per 1M tokens; "+" means any account or library voice id is accepted. [Text-to-speech guide](/guides/tts/).

| Model | List price | Formats | Voices |
| --- | --- | --- | --- |
| `openai/gpt-4o-mini-tts` | $0.6 text in · $12 audio out | mp3, opus, aac, flac, wav, pcm, mulaw, alaw | 13 |
| `openai/tts-1` | $15 per 1M chars | mp3, opus, aac, flac, wav, pcm, mulaw, alaw | 9 |
| `openai/tts-1-hd` | $30 per 1M chars | mp3, opus, aac, flac, wav, pcm, mulaw, alaw | 9 |

## Live voice

Speech-to-speech sessions in the vendor's own protocol (`openai-realtime`). Prices
per 1M tokens. [Live voice guide](/guides/live/).

| Model | List price |
| --- | --- |
| `openai/gpt-realtime-2.1` | $4 text in · $0.4 cached text in · $32 audio in · $0.4 cached audio in · $5 image in · $0.5 cached image in · $24 text out · $64 audio out |
| `openai/gpt-realtime-2.1-mini` | $0.6 text in · $0.06 cached text in · $10 audio in · $0.3 cached audio in · $0.8 image in · $0.08 cached image in · $2.4 text out · $20 audio out |
| `openai/gpt-realtime-2` | $4 text in · $0.4 cached text in · $32 audio in · $0.4 cached audio in · $5 image in · $0.5 cached image in · $24 text out · $64 audio out |
| `openai/gpt-realtime-1.5` | $4 text in · $0.4 cached text in · $32 audio in · $0.4 cached audio in · $5 image in · $0.5 cached image in · $16 text out · $64 audio out |
| `openai/gpt-realtime` | $4 text in · $0.4 cached text in · $32 audio in · $0.4 cached audio in · $5 image in · $0.5 cached image in · $16 text out · $64 audio out |
| `openai/gpt-realtime-mini` | $0.6 text in · $0.06 cached text in · $10 audio in · $0.3 cached audio in · $0.8 image in · $0.08 cached image in · $2.4 text out · $20 audio out |

## Provider options

Reach past the unified surface with [`provider_params`](/guides/streaming/#query-parameters)
— forwarded streaming → session fields; batch → form fields. Typed in the SDKs as
`{provider}Params` interfaces (`providerParams` option / `provider_params=` kwarg).

| Param | Type | Default | Applies to | What it does |
| --- | --- | --- | --- | --- |
| `prompt` | string | — | batch | Context/spelling hints for the transcription |
| `temperature` | number | — | batch | Sampling temperature |
| `timestamp_granularities[]` | `word` · `segment` | — | batch | whisper-1 with verbose output only |
| `chunking_strategy` | string | — | batch | Required by the diarize model for audio over 30s ("auto") |
| `known_speaker_names[]` | array | — | batch | Diarize model: enroll up to 4 named speakers |
| `known_speaker_references[]` | array | — | batch | Reference audio for enrolled speakers |
| `delay` | `minimal` · `low` · `medium` · `high` · `xhigh` | — | streaming | gpt-realtime-whisper: latency/quality knob |
| `turn_detection` | object | — | streaming | server_vad {threshold, silence_duration_ms} or semantic_vad {eagerness} |

## Try it

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=openai/whisper-1 \
  -F file=@audio.wav
```

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
