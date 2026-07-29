# SpeechRouter

**One API for every speech model.** Route speech-to-text across 12 providers —
Deepgram, Soniox, AssemblyAI, Speechmatics, OpenAI, Groq, Mistral, Cartesia,
ElevenLabs, Azure, AWS, Google — with one key, one schema, and **mid-stream
failover** no single vendor can give you.

```
wss://api.speechrouter.ai/v1/listen?model=deepgram/nova-3&fallbacks=soniox/stt-rt-v5
```

Your primary dies mid-utterance? The gateway replays buffered audio into the
fallback and keeps the transcript flowing — the client sees a
`provider_switched` event, not an outage. Switching vendors is a string edit.

[**Get a key**](https://speechrouter.ai) · [**Live models & pricing**](https://speechrouter.ai/models) · [**Protocol spec**](packages/spec) · Apache-2.0, self-hostable

---

## Quickstart

**TypeScript** — `npm install speechrouter`

```ts
import { SpeechRouter } from "speechrouter";

const sr = new SpeechRouter({ apiKey: "sk_sr_..." });
const stream = sr.listen({ model: "deepgram/nova-3", fallbacks: ["soniox/stt-rt-v5"] });

stream.on("transcript", (t) => t.is_final && console.log(t.text));
stream.sendAudio(pcmChunk);                 // 16-bit PCM, 16 kHz mono
const { usage } = await stream.stop();
```

**Python** — `pip install speechrouter`

```python
from speechrouter import SpeechRouter, Transcript

sr = SpeechRouter(api_key="sk_sr_...")
async with sr.listen(model="deepgram/nova-3", fallbacks=["soniox/stt-rt-v5"]) as stream:
    await stream.send_audio(pcm)
    async for event in stream:
        if isinstance(event, Transcript) and event.is_final:
            print(event.text)
```

**Batch** — POST a file, get text / verbose json / srt / vtt:

```sh
curl https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer sk_sr_..." \
  -F file=@meeting.wav -F model=groq/whisper-large-v3 -F response_format=srt
```

## Why a router

- **No single point of failure.** Every streaming session can carry an ordered
  fallback lane. A ring buffer replays recent audio into the takeover provider,
  and duplicate finals are suppressed — you don't lose words at the seam.
- **One schema.** Every provider's output is normalized to one transcript
  event: text, word timings, confidence, speakers, language. `include_raw=true`
  attaches the untouched vendor payload when you need it.
- **One bill, per-second pricing.** No per-vendor contracts or minimums.
  Bring your own provider keys (BYOK) and pay a 5% routing fee instead.
- **Same params everywhere.** Diarization, interim results, keyterm boosting,
  endpointing — expressed once, translated per provider. `provider_params`
  passes anything vendor-specific straight through.
- **Open source, self-hostable.** This repo is the exact gateway the cloud
  runs. `docker compose up` and it's yours.

## Providers

| Provider | Streaming | Batch | Notes |
|---|---|---|---|
| Deepgram | ✅ | ✅ | incl. Flux turn-based models |
| Soniox | ✅ | ✅ | token-level rewrites normalized |
| AssemblyAI | ✅ | ✅ | universal-streaming |
| Speechmatics | ✅ | ✅ | |
| OpenAI | ✅ | ✅ | realtime transcription sessions |
| Groq | — | ✅ | whisper at commodity prices |
| Mistral | ✅ | ✅ | voxtral realtime |
| Cartesia | ✅ | ✅ | incl. ink-2 turn protocol |
| ElevenLabs | ✅ | ✅ | scribe |
| Azure Speech | ✅ | ✅ | streaming needs the `[azure]` extra |
| AWS Transcribe | ✅ | soon | native SigV4 event-stream codec |
| Google Cloud STT | ✅ | soon | gRPC v2, needs the `[google]` extra |

Full catalog with live pricing: [speechrouter.ai/models](https://speechrouter.ai/models)

## Self-hosting

```sh
git clone https://github.com/speech-router/speechrouter
cd speechrouter/deploy
cp .env.example .env      # your provider keys
docker compose up
# gateway ready — ws://localhost:8080/v1/listen
```

The same image powers the hosted cloud; behavior is selected by env
(`SPEECHROUTER_KEYSTORE`, `SPEECHROUTER_USAGE_EMITTER`). Self-host mode needs
no database — keys come from env, usage goes to structured logs.

## Architecture

```
                        ┌────────────────────────────────────────┐
 client ──ws/http──►    │  gateway (FastAPI, Python 3.14)        │
   /v1/listen           │   auth → resolve → session engine      │
   /v1/audio/transcr.   │   ┌──────────────────────────────┐     │
   /v1/models           │   │ ring buffer · failover ·     │     │──► provider adapters
                        │   │ dedup · usage metering       │     │    (12 vendors, ws/grpc/rest)
                        │   └──────────────────────────────┘     │
                        └────────────────────────────────────────┘
```

- `gateway/` — the data plane. Provider adapters are one class each,
  registered against a JSON catalog; the session engine owns failover,
  timestamps, and billing so adapters stay thin.
- `packages/spec/` — JSON Schemas for every wire event and error code.
  **Source of truth**: gateway models are code-generated from it, SDK types
  mirror it, CI fails on drift.
- `packages/sdk-ts/`, `packages/sdk-python/` — official SDKs
  (npm/PyPI: `speechrouter`).
- `docs/providers/` — primary-source protocol notes for each vendor, kept as
  engineering ground truth.

## Contributing

Adapters are deliberately small — a new provider is one class plus a catalog
entry. See [CONTRIBUTING.md](CONTRIBUTING.md). We sign off commits with the
[DCO](https://developercertificate.org).

## Security

Found a vulnerability? See [SECURITY.md](SECURITY.md) — please don't open a
public issue.

## License

[Apache-2.0](LICENSE)
