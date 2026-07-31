---
title: Errors & close codes
description: The closed, stable set of error codes on both surfaces.
---

One error vocabulary everywhere. REST wraps codes in an OpenAI-compatible
envelope; the WebSocket emits an `error` event (and closes with code `1008`
after terminal errors).

```json
{ "error": { "code": "insufficient_credits", "message": "…", "type": "invalid_request_error" } }
{ "type": "error", "code": "provider_timeout", "message": "…", "recoverable": false }
```

## Codes

| Code | Meaning | Retry? |
| --- | --- | --- |
| `auth_failed` | Missing, malformed, or unknown credentials | fix key |
| `key_revoked` | Key was revoked in the console | fix key |
| `insufficient_credits` | Prepaid balance is empty | top up |
| `rate_limited` | Too many requests | back off |
| `concurrency_exceeded` | Too many simultaneous streams | back off |
| `invalid_request` | Malformed parameters | fix request |
| `model_not_found` | Unknown slug, or model lacks the requested mode | fix slug |
| `unsupported_capability` | Model can't do what you asked (e.g. diarization) | change model |
| `unsupported_encoding` | Model can't take your encoding/sample rate | change encoding |
| `payload_too_large` | Batch file over 250 MB | split audio |
| `provider_error` | Upstream vendor failed | retry / add fallbacks |
| `provider_timeout` | Upstream vendor timed out | retry |
| `all_providers_failed` | Every model in the failover lane failed | retry shortly |
| `audio_timeout` | 60s with no audio or keepalive | send keepalives |
| `session_expired` | Session exceeded its maximum lifetime | reconnect |
| `internal_error` | Our bug — alerts fire | retry |

## Provider failures on platform keys

When a vendor fails on our keys, the message is deliberately generic ("the
provider is temporarily unavailable — our team has been alerted…") — vendor
account details are ours to handle, and an alert has already paged us. On
[BYOK](/guides/byok/) sessions you get the vendor's raw error instead, because
the account is yours.
