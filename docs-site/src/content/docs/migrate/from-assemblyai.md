---
title: From AssemblyAI
description: Keep the models, gain eleven providers — the mapping.
---

Your AssemblyAI models are on SpeechRouter (`assemblyai/universal-3-5-pro`,
`universal-streaming-*`, `universal-2`) at AssemblyAI's own list prices — so
migration is a wire-format change, not a model change. You gain the other
eleven providers, mid-stream failover, and one bill.

## Streaming

| AssemblyAI v3 | SpeechRouter |
| --- | --- |
| `wss://streaming.assemblyai.com/v3/ws?...` | `wss://api.speechrouter.ai/v1/listen?model=assemblyai/universal-3-5-pro` |
| `Authorization: <key>` header | `Bearer` header or `['bearer', key]` subprotocol |
| `Turn` messages, accumulate by `turn_order` | `transcript` events with plain `is_final` |
| `end_of_turn && turn_is_formatted` dance | just `is_final: true` (the gateway dedupes the formatted/unformatted double) |
| chunk sizing 50–1000 ms + realtime pacing rules | send at any cadence — the gateway coalesces and re-paces |
| letter speakers `"A"` | integer speakers `0` |
| temp tokens via `/v3/token` | [`POST /v1/tokens`](/authentication/#short-lived-client-tokens) |

Vendor knobs (`end_of_turn_confidence_threshold`, `format_turns`, PII
redaction …) keep working via typed
[`provider_params`](/providers/assemblyai/#provider-options).

## Batch

`POST /v2/transcript` + polling becomes one synchronous call:

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=assemblyai/universal-2 -F diarization=true \
  -F response_format=verbose_json -F file=@call.mp3
```

No `upload_url` step, no polling loop — the response is the transcript.

## Keep your AssemblyAI account (optional)

[BYOK](/guides/byok/): paste your AssemblyAI key in the console and sessions
on their models run on your account, billed by SpeechRouter at $0.00.
