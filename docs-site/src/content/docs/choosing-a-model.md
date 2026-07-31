---
title: Which model should I use?
description: Opinionated picks by job — latency, languages, price, diarization.
---

Twelve providers is a lot of menu. Start from the job:

## Live voice agents

| Pick | Why |
| --- | --- |
| `soniox/stt-rt-v5` | Semantic endpointing (pause + intonation), 60+ languages, $0.12/session-hr |
| `deepgram/nova-3` | Lowest cost with tunable endpointing, huge encoding support |
| `assemblyai/universal-3-5-pro` | Turn model built for agents, `min_latency` mode |
| `cartesia/ink-2` | Server-driven turns with an eager-end signal for LLM head-start |

Always add a fallback from a *different* provider — agents must not go deaf.

## Live captions / dictation

`deepgram/nova-3` for English speed and price; `soniox/stt-rt-v5` when the
room might switch languages mid-sentence; `elevenlabs/scribe_v2_realtime`
for 90+ languages at ~150 ms.

## Batch: accuracy first

`openai/gpt-4o-transcribe` (LLM-grade), `assemblyai/universal-2`, or
`speechmatics/enhanced` (strong on accents; medical tier).

## Batch: price first

| Pick | Price | Catch |
| --- | --- | --- |
| `groq/whisper-large-v3-turbo` | $0.04/hr | 10s minimum/request, no diarization |
| `speechmatics/melia-1` | $0.129/hr | batch only |
| `openai/gpt-4o-mini-transcribe` | $0.003/min | no word timestamps |
| `mistral/voxtral-mini` | $0.003/min | 13 languages; 3h files in one request |

## Multilingual / code-switching

`speechmatics/melia-1` (56 languages, switches mid-utterance, auto-detect),
`soniox/stt-rt-v5` (streaming), `assemblyai/universal-streaming-multilingual`
(streaming, en/es/fr/de/it/pt).

## Speaker labels

Word-level: `deepgram/nova-3`, `soniox/stt-rt-v5`, `assemblyai/universal-2`,
`speechmatics/*`, `elevenlabs/scribe_v2`. Turn-level with enrollment (name
known speakers): `openai/gpt-4o-transcribe-diarize`. Streaming diarization
billed separately on Azure: `azure/conversation-transcription`.

## Telephony (8 kHz mulaw)

`deepgram/nova-3`, `soniox/stt-rt-v5`, `assemblyai/universal-3-5-pro`,
`aws/transcribe-streaming` — all take mulaw natively. Recipe:
[Transcribe phone calls](/recipes/telephony/).

## When in doubt

Start with `deepgram/nova-3` + `fallbacks=soniox/stt-rt-v5`, ship, and let
real traffic decide. Switching later is a one-line change — that's the point.
