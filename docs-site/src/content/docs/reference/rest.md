---
title: REST API
description: Every HTTP endpoint — transcriptions, speech, tokens, models, health.
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

## POST /v1/audio/speech

Text-to-speech, OpenAI-compatible. JSON body; Bearer auth; audio streams back
with chunked transfer. Fields, formats and voices:
[Text-to-speech](/guides/tts/).

## POST /v1/tokens

Mint a [short-lived client token](/authentication/#short-lived-client-tokens).
Bearer auth with a full API key (tokens cannot mint tokens).

| Body field | Default | Range |
| --- | --- | --- |
| `ttl_seconds` | 60 | 10–300 |

Returns `{ "token": "st_…", "expires_at": "…", "ttl_seconds": 60 }`.

## POST /v1/realtime/client_secrets

OpenAI-shaped alias for browser [live sessions](/guides/live/). The body's
`expires_after.seconds` is clamped to 10–300. Returns
`{ "value": "st_…", "expires_at": <unix seconds>, "session": {…} }`. The
`session` you send is echoed back; it is not pinned to the token.

## GET /v1/models

The live catalog — no auth required. Each entry carries the slug, display
name, `kind` (`stt` / `tts` / `live`), `modes` (`streaming` / `batch` /
`live`), capabilities, and pricing in the vendor's native unit:

```json
{
  "slug": "soniox/stt-rt-v5",
  "modes": ["streaming"],
  "pricing": { "per_session_hour_usd": 0.12 },
  "capabilities": { "diarization": true, "word_timestamps": true, "...": "..." }
}
```

TTS and live models price per character or per million tokens by modality,
and can carry dated price changes:

```json
{
  "slug": "gemini/gemini-3.8-flash-tts",
  "kind": "tts",
  "pricing": { "per_1m_text_input_tokens_usd": 0.5, "per_1m_audio_output_tokens_usd": 9.0 },
  "pricing_schedule": [{ "effective_from": "2027-01-01",
    "pricing": { "per_1m_text_input_tokens_usd": 1.0, "per_1m_audio_output_tokens_usd": 18.0 } }]
}
```

`pricing` is always the rate in force today. The catalog is the billing
engine's own source of truth: what it says is what you pay.

## POST /v1/listen

Deepgram-compatible prerecorded transcription (`Token` auth scheme) — see
[Deepgram compatibility](/guides/deepgram-compat/).

## GET /up

Health probe. `200` when the gateway is serving.
