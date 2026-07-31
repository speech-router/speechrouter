---
title: Deepgram compatibility
description: Point the Deepgram SDK at SpeechRouter and keep your code.
---

The gateway natively speaks the Deepgram dialect — live and prerecorded — on
the same `/v1/listen` endpoints. Existing Deepgram code migrates by changing
**the URL and the key**, nothing else.

## How dialect selection works

The auth scheme picks the dialect:

- `Authorization: Token <key>` → **Deepgram dialect** (what the Deepgram SDK sends)
- `Authorization: Bearer <key>` → native SpeechRouter schema

## Live streaming with @deepgram/sdk

```js
import { createClient, LiveTranscriptionEvents } from '@deepgram/sdk'

const dg = createClient(SPEECHROUTER_KEY, {
  global: { websocket: { options: { url: 'wss://api.speechrouter.ai' } } },
})

const live = dg.listen.live({ model: 'nova-3', interim_results: true })
live.on(LiveTranscriptionEvents.Transcript, (t) => {
  console.log(t.channel.alternatives[0].transcript)
})
```

You get Deepgram-shaped events — `Results`, `SpeechStarted`, `UtteranceEnd`,
`Metadata` — with `is_final` / `speech_final` semantics preserved, plus
`CloseStream` and `KeepAlive` handled as Deepgram defines them.

**The unlock:** `model` accepts any SpeechRouter slug. `model: 'nova-3'` routes
to Deepgram as usual; `model: 'soniox/stt-rt-v5'` routes to Soniox — through
the unchanged Deepgram SDK.

## Prerecorded

`POST /v1/listen` with `Token` auth accepts Deepgram's prerecorded shape and
returns Deepgram-shaped JSON (`results.channels[0].alternatives[0]`).

## Working example

A complete Next.js app using the Deepgram SDK against SpeechRouter, with a
model picker across providers:
[speech-router/deepgram-sdk-example](https://github.com/speech-router/deepgram-sdk-example).
