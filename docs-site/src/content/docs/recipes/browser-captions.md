---
title: Live captions in the browser
description: Mic to captions with a short-lived token — no key in the client.
---

Two pieces: a server route that mints a [client token](/authentication/#short-lived-client-tokens),
and a page that streams the mic. Your API key never leaves the server.

## 1. Token route (server)

```ts
// app/api/token/route.ts (Next.js)
import { SpeechRouter } from 'speechrouter'

const sr = new SpeechRouter({ apiKey: process.env.SPEECHROUTER_API_KEY! })

export async function POST() {
  const token = await sr.createToken({ ttlSeconds: 120 })
  return Response.json(token)
}
```

## 2. Mic to captions (browser)

```ts
import { SpeechRouter } from 'speechrouter'

const { token } = await fetch('/api/token', { method: 'POST' }).then(r => r.json())
const sr = new SpeechRouter({ apiKey: token })

const stream = sr.listen({ model: 'deepgram/nova-3', sampleRate: 16000 })
stream.on('transcript', (t) => {
  caption.textContent = t.text
  caption.classList.toggle('final', t.is_final)
})

// mic → 16-bit PCM
const media = await navigator.mediaDevices.getUserMedia({ audio: true })
const ctx = new AudioContext({ sampleRate: 16000 })
await ctx.audioWorklet.addModule('/pcm-worklet.js')
const source = ctx.createMediaStreamSource(media)
const node = new AudioWorkletNode(ctx, 'pcm16')
node.port.onmessage = (e) => stream.sendAudio(e.data)
source.connect(node)
```

```js
// public/pcm-worklet.js — float32 → int16
class PCM16 extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0][0]
    if (ch) {
      const out = new Int16Array(ch.length)
      for (let i = 0; i < ch.length; i++)
        out[i] = Math.max(-1, Math.min(1, ch[i])) * 0x7fff
      this.port.postMessage(out.buffer, [out.buffer])
    }
    return true
  }
}
registerProcessor('pcm16', PCM16)
```

The SDK authenticates over the WebSocket subprotocol, so the token never
appears in a URL or access log. Tokens gate the **handshake** only — a
2-minute TTL comfortably covers hours-long sessions.

A complete working app (using the Deepgram SDK flavor of this pattern):
[speech-router/deepgram-sdk-example](https://github.com/speech-router/deepgram-sdk-example).
