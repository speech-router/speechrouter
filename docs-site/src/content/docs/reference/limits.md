---
title: Limits
description: Session guards, payload caps, and concurrency — the numbers.
---

| Limit | Value | On breach |
| --- | --- | --- |
| Concurrent streams | 20 per organization | `concurrency_exceeded` |
| Session length | 4 hours | `session_expired` |
| Idle (no audio, no keepalive) | 60 seconds | `audio_timeout` |
| Batch payload (file or URL) | 250 MB | `payload_too_large` |
| Client token TTL | 10–300 s (default 60) | `invalid_request` |
| Keyterms | vendor-specific caps | forwarded up to cap |
| Signup rate | 5 accounts/hour/IP | HTTP 429 |
| Credit metering | every ~30s per running stream | `insufficient_credits` mid-session at $0 |

Need more concurrent streams? Write [info@speechrouter.ai](mailto:info@speechrouter.ai) —
the cap is a safety default, not a business model.

Self-hosting? All of these are env-tunable — see
[Self-hosting](/guides/self-hosting/).
