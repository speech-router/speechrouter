---
title: Bring your own keys
description: Run sessions on your own provider accounts — SpeechRouter charges nothing.
---

If you already have a contract or free credits with a provider, plug your own
key in: sessions for that provider run on **your** account and SpeechRouter
bills **$0.00** for them — routing, failover, and the unified schema included.
Pure pass-through, no routing fee.

## Setup

Console → **Settings → Organization → Provider keys**: pick the provider, paste
its API key. From that moment every session your org runs against that
provider uses your key. Remove it any time to fall back to platform keys at
list price.

Keys are encrypted at rest; the gateway reads them at session start only.

## What changes with BYOK

| | Platform keys | Your key |
| --- | --- | --- |
| Billing | vendor list price, 0% markup | **$0.00** |
| Provider errors | sanitized (our account, our problem) | raw vendor errors (your account) |
| Failover, schema, tokens | ✓ | ✓ |

Note the error behavior: on your own key you see the vendor's raw error
message, because acting on it (quota, billing, permissions) is on your side.

## Not yet supported

AWS, Azure, and Google need multi-field credentials (region, account id, …) —
BYOK for those is on the roadmap.
