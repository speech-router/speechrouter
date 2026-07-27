# Other STT providers — capability notes (2026-07-27)

- **Gladia (Solaria)**: two-step session — `POST https://api.gladia.io/v2/live` (x-gladia-key) with full config → returns {id, url} with embedded temp token → connect WS. Partials <103ms. solaria-1 / solaria-3 (EU langs). 100+ langs, diarization/NER included. ~$0.75/hr realtime starter, ~$0.25/hr committed. Distinctive: config via REST not WS/query.
- **NVIDIA Riva/NIM**: gRPC only (parakeet RNNT streaming, canary offline). Product motion = self-hosted GPU containers, no hosted per-minute WS. Defer.
- **Rev AI**: `wss://api.rev.ai/speechtotext/v1/stream`, Reverb models, batch $0.20/hr, streaming ~$0.003/min. Mature, not latency leader. Tier 2.
- **Sarvam**: 11 Indic langs + Indian English; saaras:v3 with `mode` (transcribe|translate|verbatim|translit|codemix). Distinctive for Indic market.
- **Fireworks**: `wss://audio-streaming.api.fireworks.ai/v1/audio/transcriptions/streaming` (+v2 early access). ~200ms; $0.0032/min streaming, batch whisper $0.0009–0.0015/min (cheapest batch anywhere). Fast batch 1hr in ~4s + diarization.
- **Kyutai (open weights)**: delayed-streams-modeling; stt-1b-en_fr (0.5s delay), stt-2.6b-en (2.5s). Word timestamps + semantic VAD. Rust WS server, 64 streams on one L40S. Best self-hosted backend candidate behind the gateway.

## Turn-protocol convergence note (design input)
Deepgram Flux, Cartesia ink-2 turns, and AssemblyAI U3.5-Pro all converge on a turn lifecycle with **eager end / resume** semantics (LLM head-start then cancel). Our spec's transcript+utterance_end model maps EndOfTurn; consider ADDITIVE spec events later: `turn.eager_end` / `turn.resumed`. v1 mapping: EndOfTurn → final transcript + utterance_end; eager events dropped unless client opts in via provider_params passthrough.
