---
title: Build a voice agent
description: The utterance_end loop — listen, detect the turn, respond.
---

The voice-agent loop is three moves: stream the caller's audio, catch the
**end of their turn**, hand the transcript to your LLM. SpeechRouter gives you
the same turn signal — `utterance_end` — on every provider, so the loop
doesn't change when the model does.

```ts
import { SpeechRouter } from 'speechrouter'

const sr = new SpeechRouter({ apiKey: process.env.SPEECHROUTER_API_KEY! })

const stream = sr.listen({
  model: 'soniox/stt-rt-v5',
  fallbacks: ['deepgram/nova-3'],          // agents should never go deaf
  sampleRate: 16000,
  providerParams: {                        // typed: SonioxParams
    endpoint_sensitivity: 0.3,             // the vendor's voice-agent preset
    endpoint_latency_adjustment_level: 2,
    max_endpoint_delay_ms: 1500,
  },
})

let turn = ''
stream.on('transcript', (t) => {
  if (t.is_final) turn += (turn ? ' ' : '') + t.text
})
stream.on('utterance_end', async () => {
  if (!turn.trim()) return
  const reply = await llm.respond(turn)    // your model, your tools
  turn = ''
  await speak(reply)                       // your TTS of choice
})
```

## Latency tuning

The knob that matters is **endpoint eagerness** — how fast the model decides
the human is done:

| Model | Knob | Fast-agent setting |
| --- | --- | --- |
| `soniox/stt-rt-v5` | `endpoint_sensitivity`, `max_endpoint_delay_ms` | `0.3`, `1500` |
| `deepgram/nova-3` | `endpointing`, `utterance_end_ms` | `300`, `1000` |
| `assemblyai/universal-3-5-pro` | `end_of_turn_confidence_threshold`, `mode` | `0.5`, `min_latency` |
| `cartesia/ink-2` | `turn_eager_end_threshold` | `0.4` (fires an early signal) |

Every knob is on the [provider pages](/providers/), typed in the SDKs.

## Barge-in

When the caller interrupts your TTS, just keep the stream open — it never
stopped listening. Kill your TTS playback on `speech_started` and the loop
handles interruption for free.

## Don't go deaf

Voice agents die when their STT dies. Always run a
[fallback lane](/guides/failover/): the stream survives a provider outage
mid-call, timestamps stay monotonic, and your turn loop never notices.
