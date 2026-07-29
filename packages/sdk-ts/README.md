# speechrouter

One API for every speech model — [speechrouter.ai](https://speechrouter.ai)

Streaming speech-to-text over WebSocket with **mid-stream provider failover**,
plus batch transcription. One key, one schema, 30+ models across 12 providers —
switch vendors by editing a string.

- **Works everywhere** — browsers, Node ≥ 18, React Native, edge runtimes
- **Zero runtime dependencies**
- **Fully typed** — every wire event and error code ships as a TypeScript type

```sh
npm install speechrouter
```

## Quickstart — live transcription

```ts
import { SpeechRouter } from "speechrouter";

const sr = new SpeechRouter({ apiKey: "sk_sr_..." });

const stream = sr.listen({
  model: "deepgram/nova-3",
  fallbacks: ["soniox/stt-rt-v5"], // primary dies mid-stream? we switch, you keep captioning
});

stream.on("open", (s) => console.log("session", s.session_id));
stream.on("transcript", (t) => {
  if (t.is_final) console.log("✔", t.text);
  else console.log("…", t.text);
});
stream.on("provider_switched", (s) =>
  console.log(`failover: ${s.from} → ${s.to}, resumed at ${s.resumed_at}s`),
);
stream.on("error", (e) => console.error(e.code, e.message));

stream.sendAudio(pcmChunk); // 16-bit linear PCM, 16 kHz mono by default

const done = await stream.stop(); // finalize → transcript tail → usage
console.log(done.usage); // { audio_seconds: 12.4, model: "deepgram/nova-3" }
```

Prefer async iteration? Every session is an `AsyncIterable` of wire events:

```ts
for await (const event of stream) {
  if (event.type === "transcript" && event.is_final) console.log(event.text);
  if (event.type === "provider_switched") console.log("failover!");
}
```

## Microphone (browser)

`speechrouter/mic` captures the default mic, resamples whatever rate the
browser gives you (96 kHz interfaces included) down to 16 kHz PCM, and pumps
it into the stream:

```ts
import { SpeechRouter } from "speechrouter";
import { openMicrophone } from "speechrouter/mic";

const stream = new SpeechRouter({ apiKey }).listen({ model: "deepgram/flux-general-en" });
const mic = await openMicrophone(stream, {
  onLevel: (rms) => (meter.style.width = `${rms * 300}px`),
});

// later:
mic.stop();
const { usage } = await stream.stop();
```

It's a separate entry point so React Native and server bundles never touch
browser APIs.

## React

```tsx
function Captions({ apiKey }: { apiKey: string }) {
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");

  useEffect(() => {
    const stream = new SpeechRouter({ apiKey }).listen({ model: "deepgram/nova-3" });
    const offT = stream.on("transcript", (t) =>
      t.is_final ? (setText((p) => p + " " + t.text), setInterim("")) : setInterim(t.text),
    );
    let mic: { stop(): void } | undefined;
    void import("speechrouter/mic").then(async (m) => (mic = await m.openMicrophone(stream)));
    return () => {
      offT();
      mic?.stop();
      stream.close();
    };
  }, [apiKey]);

  return <p>{text} <i>{interim}</i></p>;
}
```

## React Native

The core client is RN-safe (global WebSocket, no Node or DOM APIs). Capture
PCM with a native module and feed the stream:

```ts
import LiveAudioStream from "react-native-live-audio-stream";
import { Buffer } from "buffer";

LiveAudioStream.init({ sampleRate: 16000, channels: 1, bitsPerSample: 16, bufferSize: 4096 });
const stream = sr.listen({ model: "deepgram/nova-3" });
LiveAudioStream.on("data", (b64) => stream.sendAudio(Buffer.from(b64, "base64")));
LiveAudioStream.start();
```

For batch uploads, pass an RN file descriptor: `{ uri, name, type }`.

## Node

```ts
import { createReadStream } from "node:fs";

// stream a file as if it were live audio
const stream = sr.listen({ model: "soniox/stt-rt-v5" });
for await (const chunk of createReadStream("call.raw", { highWaterMark: 8000 })) {
  stream.sendAudio(chunk);
  await new Promise((r) => setTimeout(r, 40)); // pace ~real-time when required
}
const { usage } = await stream.stop();
```

Node 22+ uses the built-in WebSocket. Node 18–21: `npm install ws`
(optional peer dependency, picked up automatically).

## Batch transcription

```ts
// simplest: { text }
const { text } = await sr.transcribe({ model: "cartesia/ink-whisper", file });

// word timings, language, duration
const verbose = await sr.transcribe({ model: "deepgram/nova-3", file, responseFormat: "verbose_json" });

// subtitles straight out
const srt = await sr.transcribe({ model: "groq/whisper-large-v3", file, responseFormat: "srt" });

// let the gateway fetch the audio itself
await sr.transcribe({ model: "deepgram/nova-3", url: "https://example.com/call.mp3" });
```

| `responseFormat` | returns |
| --- | --- |
| `json` (default) | `{ text }` |
| `verbose_json` | text + words with timings + language + duration |
| `srt` / `vtt` | subtitle file as a string — synthesized from word timings even when the vendor won't |
| `text` | plain string |

`file` accepts a `File`/`Blob`, `Uint8Array`/`ArrayBuffer`, or a React Native
descriptor `{ uri, name, type }`. Files up to 250 MB.

## Models

```ts
const models = await sr.listModels();
// [{ slug: "deepgram/nova-3", modes: ["streaming","batch"], pricing: {...}, capabilities: {...} }, ...]
```

Live catalog with pricing: [speechrouter.ai/models](https://speechrouter.ai/models)

## `listen()` options

| option | default | |
| --- | --- | --- |
| `model` | — | model slug, e.g. `"deepgram/nova-3"` |
| `fallbacks` | `[]` | ordered failover lane; audio is replayed into the takeover so no words are lost |
| `encoding` | `"linear16"` | PCM encoding of the audio you send |
| `sampleRate` | `16000` | sample rate of the audio you send |
| `channels` | `1` | channel count |
| `language` | auto | BCP-47 hint |
| `interimResults` | `true` | emit non-final hypotheses |
| `diarization` | `false` | speaker labels on words |
| `keyterms` | `[]` | bias recognition toward these terms |
| `includeRaw` | `false` | attach the untouched provider payload to every transcript |
| `providerParams` | `{}` | escape hatch: raw params forwarded to the provider |
| `connectTimeoutMs` | `10000` | dial timeout |
| `keepAlive` | `true` (8s) | keep the session alive through silences; `false` to disable — an open session bills wall-clock time on session-billed providers |

## Events

| event | payload | when |
| --- | --- | --- |
| `open` | `session_id`, `model` | gateway accepted the session |
| `transcript` | `is_final`, `text`, `words[]` (`w`,`start`,`end`,`conf`,`speaker`), `provider_raw?` | hypothesis or final |
| `provider_switched` | `from`, `to`, `resumed_at`, `speaker_mapping_preserved` | mid-stream failover happened |
| `done` | `usage.audio_seconds`, `usage.model` | session complete — also resolves `stream.done()` |
| `error` | `SpeechRouterError` | anything went wrong |
| `close` | `code?`, `reason?` | socket closed (always last) |
| `event` | any wire event | firehose — includes `speech_started`, `utterance_end`, `text.delta`, … |

**`ListenStream` methods:** `sendAudio(chunk)` (queued if the socket isn't open
yet) · `finalize()` · `stop()` → usage · `close()` · `done()` · `bufferedAmount`
· `state` · `session`.

## Errors

Everything throws or emits `SpeechRouterError`:

```ts
try {
  await sr.transcribe({ model: "deepgram/nova-3", file });
} catch (e) {
  if (e instanceof SpeechRouterError && e.code === "insufficient_credits") topUp();
}
```

| `code` | meaning |
| --- | --- |
| `auth_failed` / `key_revoked` | bad or revoked API key |
| `insufficient_credits` | balance empty — top up |
| `concurrency_exceeded` | too many simultaneous streams for your org |
| `model_not_found` / `unsupported_capability` / `unsupported_encoding` | request can't be routed as asked |
| `invalid_request` / `payload_too_large` | malformed input / file over 250 MB |
| `provider_error` / `provider_timeout` | upstream vendor failed (`e.provider` says which); with fallbacks these become a `provider_switched` instead |
| `all_providers_failed` | primary and every fallback failed |
| `audio_timeout` | no audio or keepalive long enough that the gateway hung up |
| `connection_failed` / `connection_closed` / `timeout` | client-side network conditions |

`e.recoverable` hints whether retrying the same request may succeed.

## Self-hosting

The gateway is Apache-2.0 and runs anywhere Docker runs. Point the SDK at yours:

```ts
new SpeechRouter({ apiKey, baseUrl: "http://localhost:8080" });
```

## Browsers & mobile: short-lived tokens

An API key shipped to a page is public — never do it. Instead, your backend
mints a short-lived token and hands it to the client:

```ts
// backend (key stays here)
const { token } = await sr.createToken({ ttlSeconds: 60 });

// client (browser / React Native)
const client = new SpeechRouter({ apiKey: token });
const stream = client.listen({ model: "deepgram/nova-3" });
```

The TTL only limits how long the token can *open* connections — a stream
that's already running continues past expiry. Default 60s, max 300s.

---

Apache-2.0 · [gateway & protocol spec](https://github.com/speech-router/speechrouter) · [console](https://speechrouter.ai) · [live models & pricing](https://speechrouter.ai/models)
