---
title: AWS
description: Amazon Transcribe streaming with per-request minimums.
sidebar: { order: 3 }
---

Amazon Transcribe streaming with per-request minimums.

All prices are the vendor's public list price — 0% markup. Extra provider
knobs pass through untouched via `provider_params`.

| Model | Modes | List price | Diarization | Word timings |
| --- | --- | --- | --- | --- |
| `aws/transcribe` | streaming | $0.01/min (min $0.0025/req) | <span class="sr-yes">✓</span> | <span class="sr-yes">✓</span> |

## Provider options

:::note
The streaming URL is SigV4-signed at connect time, so arbitrary extra query params cannot be forwarded. Language, diarization, and encoding are set via the standard SpeechRouter params.
:::

## Try it

```text
wss://api.speechrouter.ai/v1/listen?model=aws/transcribe
```
Streaming-only — connect with the [SDKs](/sdks/javascript/) or see [Streaming](/guides/streaming/).

<sub>Generated from the gateway catalog — the billing engine's own source of truth.</sub>
