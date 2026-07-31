---
title: Introduction
description: What SpeechRouter is, how it is shaped, and what it promises.
---

SpeechRouter is a unified gateway for speech-to-text: **one API in front of 12
providers** (Deepgram, Soniox, AssemblyAI, OpenAI, Speechmatics, Azure, AWS,
Google, Groq, Mistral, ElevenLabs, Cartesia). You hold one key, learn one
schema, and get one bill — and every model on the market is a slug away.

## Why it exists

Speech vendors disagree on everything: auth schemes, WebSocket dialects, event
shapes, timestamp units, pricing units. Teams either marry one vendor or
maintain N integrations. SpeechRouter absorbs that variance at the gateway:

- **One request shape** — the same query params and form fields for every model.
- **One event schema** — normalized transcripts, words, timestamps, and speakers.
- **One failure model** — a closed set of [error codes](/reference/errors/), with
  automatic [failover](/guides/failover/) when a provider dies mid-stream.

## The three surfaces

| Surface | What it does |
| --- | --- |
| `wss://api.speechrouter.ai/v1/listen` | [Live streaming transcription](/guides/streaming/) |
| `POST /v1/audio/transcriptions` | [Batch file / URL transcription](/guides/batch/) |
| `GET /v1/models` | The live [model catalog](/providers/) with prices and capabilities |

Everything is open source ([speech-router/speechrouter](https://github.com/speech-router/speechrouter),
Apache-2.0) and self-hostable; the hosted gateway at `api.speechrouter.ai` is the
zero-ops path.

## What it costs

Vendor list price, 0% markup — the catalog carries each vendor's own pricing in
its native unit and we charge exactly that. Details in
[Pricing & billing](/guides/pricing/).
