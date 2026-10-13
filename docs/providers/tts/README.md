# TTS provider notes (phase 2)

One file per vendor, researched from official docs and pricing pages on 2026-10-13.
These are the review artifact for each adapter in `gateway/speechrouter_gateway/providers/<id>/tts.py`.
Anything marked **UNVERIFIED** still needs a live check; run `scripts/tts_provider_probe.py`
once keys exist.

| Provider | Adapter | Status |
|---|---|---|
| ElevenLabs, Cartesia, Deepgram, Azure, Google, Rime, Inworld, Fish Audio, MiniMax, Groq, Murf, Speechmatics | yes | in catalog (mock-tested; live pending keys) |
| LMNT | no | **shut down** (lmnt.com) |
| PlayHT | no | **shut down** (Meta acquired PlayAI in 2025; API domains don't resolve) |
| Hume | no | TTS API **sunsets 2026-11-13**; pricing unverifiable |
| Resemble | no | no verifiable public list price |
| xAI Grok TTS, Deepgram Flux | yes (REST plus **native socket** for `/v1/speak`) | phase 3, in catalog (mock-tested) |
| Amazon Polly (standard/neural/long-form/generative) | yes (SynthesizeSpeech, SigV4) | phase 3, **mock-only by decision**; bidirectional stream is a follow-up |
| Mistral Voxtral, Smallest.ai Lightning, Kokoro (Together) | yes | phase 3, in catalog (mock-tested) |
| Telnyx (Kokoro / NaturalHD) | no | Kokoro price line only inferable from the pricing page and no mu-law documented; Together chosen for the Kokoro tier |
