---
title: Pricing & billing
description: Vendor list price, 0% markup, native units, and how sessions meter.
---

The pricing model is one sentence: **you pay exactly what the provider charges
us, at their public list price, and we add nothing.**

## Native units

Each model is priced in its vendor's own unit — no lossy conversions:

| Unit | Example |
| --- | --- |
| per audio-minute | `deepgram/nova-3` — $0.0048/min |
| per audio-hour | `speechmatics/melia-1` — $0.129/hr |
| per session-hour | `soniox/stt-rt-v5` — $0.12/hr **wall-clock** |
| minimum per request | `aws/*` — 15s minimum, `groq/*` — 10s minimum |

**Session-billed models** (Soniox realtime, AssemblyAI streaming) meter on
wall-clock connection time — an open socket bills even when silent, because
that's how the vendor bills us. Everything else meters on audio duration.

Current prices for every model: [`GET /v1/models`](/reference/rest/#get-v1models)
or the [providers pages](/providers/) — both are generated from the same
catalog the billing engine uses, so they cannot drift from what you're charged.

## Credits

Prepaid credits, minimum $5 top-up via Stripe, never expire. New accounts get a
$2 welcome credit on email verification. When the balance hits zero, new
sessions are rejected with `insufficient_credits` (running sessions finish).

## The ledger

Every session writes a usage event with the model, audio seconds, billed
seconds, and price in micro-dollars — visible in the console's billing ledger.
Sub-cent amounts display to five decimals; we never round a real debit to
a lying $0.00.

[BYOK](/guides/byok/) sessions bill $0.00.
