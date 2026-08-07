---
title: Self-hosting
description: Run the gateway on your own metal — Apache-2.0, one process, your keys.
---

The gateway is Apache-2.0 and runs as a single process. Self-hosting gives you
the unified API and failover on your own infrastructure, with your own
provider accounts — no SpeechRouter account involved.

## Run it

```bash
git clone https://github.com/speech-router/speechrouter
cd speechrouter/gateway
uv sync                                # Python 3.13+
uv run uvicorn speechrouter_gateway.main:app --port 8080
```

Or containerized (the image behind api.speechrouter.ai):

```bash
docker build -f deploy/Dockerfile -t speechrouter-gateway .
docker run -p 8080:8080 --env-file gateway/.env speechrouter-gateway
```

Azure realtime needs the SDK extra — it's baked into the Docker image; for
bare-metal add it with `uv sync --extra azure`.

## Configuration

Everything is env vars with the `SPEECHROUTER_` prefix (or a `.env` file):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPEECHROUTER_KEYSTORE` | `local` | `local` = static keys; `cloud` = Redis-backed console keys |
| `SPEECHROUTER_KEYS` | — | Local mode: comma-separated API keys you invent (`sk_local_abc`) |
| `SPEECHROUTER_USAGE_EMITTER` | `log` | `log` = structured line per session; `redis` = usage stream |
| `SPEECHROUTER_REDIS_URL` | `redis://localhost:6379/0` | Only for `cloud` keystore / `redis` emitter |
| `SPEECHROUTER_MAX_CONCURRENT_STREAMS` | `20` | Per key; `0` = unlimited |
| `SPEECHROUTER_MAX_SESSION_SECONDS` | `14400` | Hard session cap (4 h) |
| `SPEECHROUTER_IDLE_TIMEOUT_SECONDS` | `60` | Close idle sessions |
| `SPEECHROUTER_AUDIO_SINK` | `none` | `none` = no persistence (also the hosted default); `s3` = stream session audio to your own bucket — see [Audio persistence](/guides/audio-persistence/) |

Provider keys — set the ones you use:

```bash
SPEECHROUTER_DEEPGRAM_API_KEY=...
SPEECHROUTER_SONIOX_API_KEY=...
SPEECHROUTER_ASSEMBLYAI_API_KEY=...
SPEECHROUTER_OPENAI_API_KEY=...
SPEECHROUTER_SPEECHMATICS_API_KEY=...
SPEECHROUTER_GROQ_API_KEY=...
SPEECHROUTER_MISTRAL_API_KEY=...
SPEECHROUTER_ELEVENLABS_API_KEY=...
SPEECHROUTER_CARTESIA_API_KEY=...
SPEECHROUTER_AZURE_SPEECH_KEY=... SPEECHROUTER_AZURE_SPEECH_REGION=...
SPEECHROUTER_AWS_ACCESS_KEY_ID=... SPEECHROUTER_AWS_SECRET_ACCESS_KEY=...
```

A model whose provider has no key simply resolves as "not configured" —
everything else keeps working.

## Point the SDKs at it

```ts
new SpeechRouter({ apiKey: 'sk_local_abc', baseUrl: 'http://localhost:8080' })
```

```python
SpeechRouter(api_key="sk_local_abc", base_url="http://localhost:8080")
```

Self-hosted, you pay providers directly on your own accounts. Usage is
observable via the `log` emitter (one structured line per session with
audio/billed seconds and model).
