---
title: REST API
description: Every HTTP endpoint — transcriptions, tokens, models, health.
---

Base URL: `https://api.speechrouter.ai`. Errors use an OpenAI-compatible
envelope with a [closed set of codes](/reference/errors/):

```json
{ "error": { "code": "model_not_found", "message": "…", "type": "invalid_request_error" } }
```

The machine-readable spec:
[`openapi.yaml`](https://github.com/speech-router/speechrouter/blob/main/packages/spec/openapi.yaml).

## POST /v1/audio/transcriptions

Batch transcription. Multipart form; Bearer auth. Fields, formats, and limits:
[Batch transcription](/guides/batch/).

## POST /v1/tokens

Mint a [short-lived client token](/authentication/#short-lived-client-tokens).
Bearer auth with a full API key (tokens cannot mint tokens).

| Body field | Default | Range |
| --- | --- | --- |
| `ttl_seconds` | 60 | 10–300 |

Returns `{ "token": "st_…", "expires_at": "…", "ttl_seconds": 60 }`.

## GET /v1/models

The live catalog — no auth required. Each entry carries the slug, display
name, `modes` (`streaming` / `batch`), capabilities, and pricing in the
vendor's native unit:

```json
{
  "slug": "soniox/stt-rt-v5",
  "modes": ["streaming"],
  "pricing": { "per_session_hour_usd": 0.12 },
  "capabilities": { "diarization": true, "word_timestamps": true, "...": "..." }
}
```

The catalog is the billing engine's own source of truth — what it says is what
you pay.

## POST /v1/listen

Deepgram-compatible prerecorded transcription (`Token` auth scheme) — see
[Deepgram compatibility](/guides/deepgram-compat/).

## GET /up

Health probe. `200` when the gateway is serving.
