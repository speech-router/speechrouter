<p align="center">
  <a href="https://speechrouter.ai"><img src="assets/brand/mark.svg" width="88" alt="SpeechRouter"></a>
</p>

<h1 align="center">SpeechRouter</h1>

<p align="center"><b>One API for every speech model.</b><br>
Streaming speech-to-text across 12 providers with mid-stream failover —<br>
one key, one schema, switch vendors by editing a string.</p>

<p align="center">
  <a href="https://www.npmjs.com/package/speechrouter"><img src="https://img.shields.io/npm/v/speechrouter?label=npm&color=E8A33D" alt="npm"></a>
  <a href="https://github.com/speech-router/speechrouter/actions"><img src="https://img.shields.io/github/actions/workflow/status/speech-router/speechrouter/ci.yml?label=ci" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0"></a>
</p>

<p align="center">
  <a href="https://speechrouter.ai"><b>Get a key</b></a> ·
  <a href="https://speechrouter.ai/models"><b>Live models & pricing</b></a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#the-streaming-protocol">Protocol</a> ·
  <a href="#self-hosting">Self-host</a>
</p>

---

Speech vendors go down mid-sentence, change prices, and each speak a different
protocol. SpeechRouter puts one gateway in front of all of them:

```
wss://api.speechrouter.ai/v1/listen?model=deepgram/nova-3&fallbacks=soniox/stt-rt-v5
```

If the primary dies mid-utterance, the gateway **replays buffered audio into the
fallback and keeps transcribing** — your client sees a `provider_switched`
event, not an outage. Suppressed duplicate finals mean no words are lost or
repeated at the seam.

- 🎛 **30+ models, 12 providers** — Deepgram (incl. Flux), Soniox, AssemblyAI, Speechmatics, OpenAI, Groq, Mistral, Cartesia (incl. ink-2 turns), ElevenLabs, Azure, AWS, Google
- 🔌 **One normalized schema** — text, word timings, confidence, speakers, language; `include_raw=true` for the untouched vendor payload
- 💸 **One bill** — per-second pricing, prepaid credits, no vendor contracts; or **BYOK** with your own provider keys for free — pure pass-through, 0% markup
- 🔁 **Same params everywhere** — diarization, interims, keyterm boosting, endpointing, translated per provider; `provider_params` passes anything vendor-specific through
- 🏠 **Apache-2.0, self-hostable** — this repo is the exact gateway the cloud runs

## Quickstart

Get a key at [speechrouter.ai](https://speechrouter.ai) — new orgs start with free credits.

### TypeScript — `npm install speechrouter`

```ts
import { SpeechRouter } from "speechrouter";

const sr = new SpeechRouter({ apiKey: "sk_sr_..." });
const stream = sr.listen({ model: "deepgram/nova-3", fallbacks: ["soniox/stt-rt-v5"] });

stream.on("transcript", (t) => t.is_final && console.log(t.text));
stream.on("provider_switched", (s) => console.log(`failover: ${s.from} → ${s.to}`));

stream.sendAudio(pcmChunk);            // 16-bit linear PCM, 16 kHz mono by default
const { usage } = await stream.stop(); // finalize → transcript tail → usage
```

Works in browsers (with a bundled [mic helper](packages/sdk-ts#microphone-browser)),
Node ≥ 18, and React Native. [Full SDK docs →](packages/sdk-ts)

### Python — PyPI package coming soon; install from the repo:

```bash
pip install "git+https://github.com/speech-router/speechrouter.git#subdirectory=packages/sdk-python"
```

```python
from speechrouter import SpeechRouter, Transcript

sr = SpeechRouter(api_key="sk_sr_...")
async with sr.listen(model="deepgram/nova-3", fallbacks=["soniox/stt-rt-v5"]) as stream:
    await stream.send_audio(pcm)
    async for event in stream:
        if isinstance(event, Transcript) and event.is_final:
            print(event.text)
```

[Full SDK docs →](packages/sdk-python)

### Batch — any HTTP client

```sh
curl https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer sk_sr_..." \
  -F file=@meeting.wav -F model=groq/whisper-large-v3 -F response_format=srt
```

`response_format`: `json` · `verbose_json` (words + timings) · `srt` · `vtt`
(synthesized from word timings even when the vendor won't) · `text`.
Files to 250 MB, or pass `url=` and the gateway fetches the audio itself.

## The streaming protocol

One WebSocket, everything else is query params:

| param | default | |
|---|---|---|
| `model` | — | slug, e.g. `deepgram/nova-3` |
| `fallbacks` | — | comma-separated failover lane |
| `encoding` / `sample_rate` / `channels` | `linear16` / `16000` / `1` | the PCM you'll send |
| `language` | auto | BCP-47 hint |
| `interim_results` | `true` | non-final hypotheses |
| `diarization` | `false` | speaker labels on words |
| `keyterms` | — | comma-separated recognition bias |
| `include_raw` | `false` | attach untouched provider payload |
| `provider_params` | — | JSON forwarded to the provider verbatim |

Send binary frames of PCM; send `{"type":"finalize"}` to flush,
`{"type":"keepalive"}` to hold the session through silence. The gateway pushes
JSON events:

| event | meaning |
|---|---|
| `session.open` | session accepted — `session_id`, resolved `model` |
| `transcript` | `is_final`, `text`, `words[]` (`w`,`start`,`end`,`conf`,`speaker`), `provider_raw?` |
| `speech_started` / `utterance_end` | voice activity edges |
| `provider_switched` | failover happened — `from`, `to`, `resumed_at` |
| `done` | session complete — `usage.audio_seconds`, billed model |
| `error` | 16-code enum (`insufficient_credits`, `concurrency_exceeded`, `provider_error`, …) + `recoverable` hint |

The JSON Schemas in [`packages/spec`](packages/spec) are the source of truth —
gateway models are code-generated from them and CI fails on drift.

## Providers

| Provider | Streaming | Batch | Notes |
|---|:-:|:-:|---|
| Deepgram | ✅ | ✅ | incl. Flux turn-based models |
| Soniox | ✅ | ✅ | token-level rewrites normalized |
| AssemblyAI | ✅ | ✅ | universal-streaming |
| Speechmatics | ✅ | ✅ | |
| OpenAI | ✅ | ✅ | realtime transcription sessions |
| Groq | — | ✅ | whisper at commodity prices |
| Mistral | ✅ | ✅ | voxtral realtime |
| Cartesia | ✅ | ✅ | incl. ink-2 turn protocol |
| ElevenLabs | ✅ | ✅ | scribe |
| Azure Speech | ✅ | ✅ | streaming via `[azure]` extra |
| AWS Transcribe | ✅ | soon | native SigV4 event-stream codec |
| Google Cloud STT | ✅ | soon | gRPC v2, via `[google]` extra |

Live catalog with per-second pricing: [speechrouter.ai/models](https://speechrouter.ai/models)

Each adapter was built from the vendor's primary docs — the research notes live
in [`docs/providers/`](docs/providers) and double as reviewable ground truth.

## Self-hosting

The hosted cloud and self-host run the **same image**; behavior is selected by env.

```sh
git clone https://github.com/speech-router/speechrouter
cd speechrouter/deploy
cp .env.example .env      # your provider keys
docker compose up
# gateway ready — ws://localhost:8080/v1/listen
```

| env | purpose |
|---|---|
| `SPEECHROUTER_KEYS` | comma-separated API keys your clients will use |
| `SPEECHROUTER_<PROVIDER>_API_KEY` | upstream credentials (`DEEPGRAM`, `SONIOX`, …) |
| `SPEECHROUTER_KEYSTORE` | `local` (env keys) or `cloud` (Redis-backed) |
| `SPEECHROUTER_USAGE_EMITTER` | `log` (structured lines) or `redis` (usage stream) |
| `SPEECHROUTER_MAX_CONCURRENT_STREAMS` | per-key cap, default 20 |

Self-host mode needs no database. Azure streaming and Google need extras:
`uv sync --extra azure --extra google`.

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

| path | what |
|---|---|
| [`gateway/`](gateway) | the data plane — session engine owns failover/timestamps/billing; adapters stay one class each |
| [`packages/spec/`](packages/spec) | JSON Schemas for every event + error code — the protocol's source of truth |
| [`packages/sdk-ts/`](packages/sdk-ts) | TypeScript SDK (npm: [`speechrouter`](https://www.npmjs.com/package/speechrouter)) |
| [`packages/sdk-python/`](packages/sdk-python) | Python SDK (PyPI: `speechrouter`) |
| [`docs/providers/`](docs/providers) | primary-source protocol notes per vendor |
| [`deploy/`](deploy) | Dockerfile + compose for self-hosting |

## Roadmap

**TTS lane** (`/v1/speak` — same router, voices out) · AWS/Google batch ·
eager-turn events · more providers (Gladia, NVIDIA Riva, Rev, Sarvam —
[the bench](https://speechrouter.ai/models)).

## Contributing

A new provider is one adapter class + a catalog entry — see
[CONTRIBUTING.md](CONTRIBUTING.md) for the recipe. Commits are signed off under
the [DCO](https://developercertificate.org).

Security reports: privately, per [SECURITY.md](SECURITY.md).

## License

[Apache-2.0](LICENSE) — route freely.
