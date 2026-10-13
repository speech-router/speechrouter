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
| Mistral Voxtral TTS, xAI, Smallest.ai | no | candidates: see `_others.md` |
