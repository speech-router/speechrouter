---
title: Transcribe phone calls
description: Twilio Media Streams to SpeechRouter — mulaw@8k, live.
---

Telephony audio is 8 kHz mulaw. Declare it and stream — no transcoding.

## Twilio Media Streams

Point a `<Stream>` at your server, relay frames to SpeechRouter:

```ts
import { SpeechRouter } from 'speechrouter'
import { WebSocketServer } from 'ws'

const sr = new SpeechRouter({ apiKey: process.env.SPEECHROUTER_API_KEY! })

new WebSocketServer({ port: 8081 }).on('connection', (twilio) => {
  const stream = sr.listen({
    model: 'deepgram/nova-3',
    fallbacks: ['soniox/stt-rt-v5'],
    encoding: 'mulaw',              // telephony native — no transcoding
    sampleRate: 8000,
  })
  stream.on('transcript', (t) => t.is_final && console.log(t.text))

  twilio.on('message', (raw) => {
    const msg = JSON.parse(raw.toString())
    if (msg.event === 'media')
      stream.sendAudio(Buffer.from(msg.media.payload, 'base64'))
    if (msg.event === 'stop') stream.finalize()
  })
})
```

```xml
<Response>
  <Start><Stream url="wss://your-server.example/twilio" /></Start>
  <Dial>+15551234567</Dial>
</Response>
```

## Both legs of the call

Twilio sends inbound and outbound tracks; open one SpeechRouter stream per
track and tag transcripts by leg — cleaner than diarization for two-party
calls, and it works on every model.

## Notes

- Models that don't accept `mulaw`/8 kHz are rejected at connect time — the
  [provider pages](/providers/) list encodings per model. `linear16`
  16 kHz-only models still work if you upsample, but native mulaw models
  (Deepgram, Soniox, AssemblyAI, ElevenLabs, AWS) are the straight path.
- Phone silence is still session time on
  [session-billed models](/guides/pricing/#native-units) — put audio-billed
  models on hold music legs.
