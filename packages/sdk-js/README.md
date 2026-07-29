# speechrouter

One API for every speech model — [speechrouter.ai](https://speechrouter.ai).

Streaming speech-to-text over WebSocket with mid-stream provider failover,
plus batch transcription. Works in browsers, Node ≥ 18, and React Native.
Zero runtime dependencies.

```sh
npm install speechrouter
```

## Streaming

```ts
import { SpeechRouter } from "speechrouter";

const sr = new SpeechRouter({ apiKey: "sk_sr_..." });

const stream = sr.listen({
  model: "deepgram/nova-3",
  fallbacks: ["soniox/stt-rt-v5"],   // dies mid-stream? we switch, you keep captioning
});

stream.on("transcript", (t) => {
  if (t.is_final) console.log(t.text);
});
stream.on("provider_switched", (s) => console.log(`failover: ${s.from} → ${s.to}`));

stream.sendAudio(pcmChunk);            // 16-bit linear PCM, 16 kHz mono by default
const { usage } = await stream.stop(); // finalize → transcript tail → usage
```

Or consume the session as an async stream:

```ts
for await (const event of stream) {
  if (event.type === "transcript" && event.is_final) console.log(event.text);
}
```

## Microphone (browser)

```ts
import { openMicrophone } from "speechrouter/mic";

const mic = await openMicrophone(stream, { onLevel: (rms) => meter.style.width = `${rms * 300}px` });
// later: mic.stop(); await stream.stop();
```

Captures the default mic, resamples whatever rate the browser gives you
(96 kHz interfaces included) down to 16 kHz PCM, and pumps it into the stream.

In React Native, capture PCM with a native module (e.g.
`react-native-live-audio-stream`) and call `stream.sendAudio(chunk)` — the
core client is RN-safe and never imports browser APIs.

## Batch

```ts
const { text } = await sr.transcribe({ model: "cartesia/ink-whisper", file });

// subtitles straight out:
const srt = await sr.transcribe({ model: "deepgram/nova-3", file, responseFormat: "srt" });
```

`file` accepts a browser `File`/`Blob`, raw bytes (`Uint8Array`/`ArrayBuffer`),
or a React Native descriptor `{ uri, name, type }`. Pass `url` instead to have
the gateway fetch the audio itself.

## Models

```ts
const models = await sr.listModels(); // slugs, capabilities, live pricing
```

## Errors

Everything throws or emits `SpeechRouterError` with a machine-readable
`code` (`insufficient_credits`, `concurrency_exceeded`, `provider_error`,
…), the upstream `provider` when known, and a `recoverable` hint.

## Self-hosting

Point the client at your own gateway:

```ts
new SpeechRouter({ apiKey, baseUrl: "http://localhost:8080" });
```

Note for browsers: an API key shipped to a page is public. Mint short-lived
keys from your backend, or proxy the socket.

Apache-2.0 · [protocol spec](https://github.com/speech-router/speechrouter/tree/main/packages/spec) · [gateway](https://github.com/speech-router/speechrouter)
