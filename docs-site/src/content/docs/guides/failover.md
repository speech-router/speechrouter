---
title: Failover
description: Ordered fallback lanes and what the gateway guarantees mid-switch.
---

Providers fail: keys get revoked, vendors change APIs, regions have bad days.
SpeechRouter treats that as routing, not as your incident.

## Declaring a lane

Pass an ordered list of fallbacks alongside your primary:

```text
wss://api.speechrouter.ai/v1/listen?model=soniox/stt-rt-v5&fallbacks=deepgram/nova-3,assemblyai/universal-3-5-pro
```

```js
sr.listen({ model: 'soniox/stt-rt-v5', fallbacks: ['deepgram/nova-3'] })
```

Every model in the lane must support your declared encoding and sample rate —
the gateway validates the whole lane at connect time and rejects impossible
lanes up front (`unsupported_capability`).

## What happens on failure

1. The primary dies (connection drop, vendor error, timeout).
2. The gateway replays its buffered audio tail into the next model in the lane —
   speech spanning the switch is not lost.
3. You receive a switch marker:
   ```json
   { "type": "provider_switched", "from": "soniox/stt-rt-v5",
     "to": "deepgram/nova-3", "resumed_at": 41.52,
     "speaker_mapping_preserved": false }
   ```
   `resumed_at` is the audio-time position the replay resumed from.
4. The stream continues. **Timestamps stay monotonic** — the new provider's
   clock is offset so `words[].start` never goes backwards — and the gateway
   **deduplicates finals**: you never receive two final transcripts covering
   the same audio range, even though the tail was replayed. Interims may
   re-cover replayed audio; the next final supersedes them as usual.

With diarization on, `speaker_mapping_preserved: false` means speaker indices
reset with the new provider — treat labels as a new epoch after a switch.

If every model in the lane fails you get a terminal
`{ "type": "error", "code": "all_providers_failed" }`.

## Billing during failover

You're billed per model actually used, at each model's own list price, split by
time on each. The usage record carries the model that served each span.

:::tip
Put vendors with **different infrastructure** in one lane. Two models from the
same provider share the same failure domain.
:::
