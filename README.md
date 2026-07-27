# SpeechRouter

**One API for every STT & TTS provider.**

A unified, OpenAI-compatible gateway for speech-to-text and text-to-speech —
realtime streaming first. Route across Deepgram, Soniox, Azure, AWS, OpenAI,
ElevenLabs, Cartesia and more with one API key, one SDK, and one normalized
transcript schema. Automatic mid-stream failover, per-model routing, BYOK,
and full self-hosting.

> 🚧 Pre-release. The protocol spec in [`packages/spec`](packages/spec) is the
> current source of truth; the gateway, SDKs, and docs are being built against it.

## Layout

| Path | What |
|---|---|
| `gateway/` | Python/FastAPI data plane: REST + WebSocket endpoints, provider adapters, routing |
| `packages/spec/` | OpenAPI + JSON Schema protocol definitions — source of truth, SDKs codegen from it |
| `packages/sdk-ts/` | TypeScript SDK (npm: `speechrouter`) |
| `packages/sdk-python/` | Python SDK (PyPI: `speechrouter`) |
| `docs/` | Documentation site |
| `deploy/` | Self-hosting: Dockerfile + docker-compose |

## License

[Apache-2.0](LICENSE)
