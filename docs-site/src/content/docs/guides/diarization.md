---
title: Diarization
description: Speaker labels — word-level vs segment-level, and failover semantics.
---

Pass `diarization=true` (query param, form field, or SDK option) on a model
whose [provider page](/providers/) shows the diarization mark. Models that
can't diarize reject at connect time with `unsupported_capability` — never
silently ignored.

## What you get

Integer speaker labels on words, normalized across providers (vendors label
`"A"/"B"`, `"Guest-1"`, or `0/1` — you always see `0, 1, 2 …`):

```json
{ "type": "transcript", "is_final": true,
  "text": "I disagree. Let me explain.",
  "words": [
    { "w": "I",       "start": 4.1, "end": 4.2, "speaker": 0 },
    { "w": "disagree","start": 4.2, "end": 4.6, "speaker": 0 },
    { "w": "Let",     "start": 5.0, "end": 5.1, "speaker": 1 }
  ] }
```

**Granularity varies by model.** Most diarizing models label every word.
Segment-level models (e.g. `openai/gpt-4o-transcribe-diarize`) return one
words-entry per speaker turn instead — same schema, coarser grain.

## Failover semantics

Speaker indices are only meaningful within one provider's run. After a
`provider_switched` event, `speaker_mapping_preserved: false` tells you the
labels restarted — speaker `0` after the switch is not necessarily speaker `0`
from before. Treat each provider span as its own labeling epoch (or re-align
in your application using overlap heuristics).

## Pricing notes

Diarization is included in the model's list price except where the vendor
meters it separately — most notably Azure, where diarized streaming is its own
product: use [`azure/conversation-transcription`](/providers/azure/)
($1.20/hr) — the $1.00 `azure/speech-realtime` refuses `diarization=true`
rather than silently billing you a different meter.
