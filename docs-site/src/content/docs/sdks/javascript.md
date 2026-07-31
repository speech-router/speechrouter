---
title: JavaScript / TypeScript
description: The speechrouter package — typed client for Node and the browser.
---

```bash
npm install speechrouter
```

Works in Node ≥ 18 and modern browsers (native `fetch` + `WebSocket`). Fully
typed, zero dependencies.

## Client

```ts
import { SpeechRouter } from 'speechrouter'

const sr = new SpeechRouter({ apiKey: process.env.SPEECHROUTER_API_KEY! })
// self-hosted? new SpeechRouter({ apiKey, baseUrl: 'https://gateway.internal' })
```

## Batch

```ts
const { text } = await sr.transcribe({
  model: 'openai/whisper-1',
  file: audioBlob,                       // File | Blob | ArrayBuffer | Uint8Array
})

// typed by responseFormat:
const verbose = await sr.transcribe({
  model: 'assemblyai/universal-2',
  file: audioBlob,
  responseFormat: 'verbose_json',        // → words[], duration, language
  diarization: true,
})
```

## Streaming

```ts
const stream = sr.listen({
  model: 'soniox/stt-rt-v5',
  fallbacks: ['deepgram/nova-3'],
  sampleRate: 16000,
})

stream.on('transcript', (t) => t.is_final && render(t.text))
stream.on('utterance_end', () => agent.respond())
stream.on('provider_switched', (e) => log(`failover → ${e.to}`))

stream.sendAudio(pcm)          // Uint8Array / ArrayBuffer of 16-bit PCM
await stream.finalize()        // flush finals, resolve on done
```

Events are also an async iterable:

```ts
for await (const event of stream) {
  if (event.type === 'transcript' && event.is_final) …
}
```

The client keepalives idle sockets automatically.

## Browser: client tokens

```ts
// server route
const { token } = await sr.createToken({ ttlSeconds: 60 })

// browser — token instead of the key, via subprotocol auth
const stream = new SpeechRouter({ apiKey: token }).listen({ model: 'deepgram/nova-3' })
```

## Errors

Failures throw `SpeechRouterError` with the gateway's
[stable code](/reference/errors/) on `.code`.
