# Live verification, 2026-10-13

Keys were in `/home/agent/agent-env/speechrouter-providers.env` for 11 providers. Real calls used one synthetic
56-character sentence per model and format. Every real sample was round-trip transcribed with Deepgram Nova-3,
and all were intelligible; only the invented word "SpeechRouter" was misheard. Total list-price spend was about $0.08.

| Question | Answer (live) | Gateway change |
|---|---|---|
| Gemini Live usage: per turn or running total? | **Per turn.** There is one `usageMetadata` per turn; `responseTokenCount` does not accumulate (44 → 47), while `promptTokenCount` re-bills the context (559 → 628). The `per_message` (sum) default is **correct**. | The modality details can sum short of `promptTokenCount` (312+222 of 559), and the remainder is now billed as text input. `thoughtsTokenCount` sits outside `totalTokenCount` and is billed as text output. |
| Gemini TTS `usageMetadata` | It arrives on every chunk (59 times) as a running total, so "last wins" is correct. Audio is 25 tokens/s. | none |
| OpenAI Realtime token rates | 10 audio tokens/s in, 20 out. `output_token_details.reasoning_tokens` is a subset of the text tokens. | none (the estimates already matched) |
| OpenAI TTS token rate | 26.8 audio tokens/s (91 tokens for 3.40 s); the marketing figure implies 20.8 | fallback estimate updated |
| Google Cloud TTS accepts an API key? | **Not testable: no `GOOGLE_CLOUD_TTS_KEY` in the env file.** | — |
| Groq formats | **Not testable**: every Orpheus call returns 400 "requires terms acceptance … org admin". | 4xx bodies about our own account are now classified `account` (hidden from customers and alerted), no longer `invalid_request` |
| Rime sample rates / Murf PCM byte order | **Not testable: no keys** | — |
| Mistral streaming format | `event: speech.audio.delta` `{type, audio_data}`, then `speech.audio.done` `{type, usage{prompt_tokens, completion_tokens, total_tokens}}`. PCM is float32 at 24 kHz. | the parser is now strict (`audio_data` only) |
| Vendor-reported characters vs text length | Deepgram Aura and Flux REST `dg-char-count` = text length (56/56). **The Flux socket after an Interrupt billed 29 of 79 characters sent.** Inworld, MiniMax and Polly: no keys (Polly mock-only by decision). | the gateway already bills the vendor count |
| Azure | Neural works. Neural HD (Dragon HD) returns **400 with an empty body**: the house resource is in westus, which lists 0 Dragon HD voices. `en-US-AvaMultilingualNeural` exists. | the error now names the cause; the catalog note says HD needs an HD-capable region |

Live OK: OpenAI (3 TTS models, Realtime), Gemini (2 TTS models, Live), ElevenLabs (7), Cartesia (3),
Deepgram (Aura-1, Aura-2, Flux REST and the Flux native socket with a barge-in), Azure Neural, Mistral and
Speechmatics, each including 8 kHz μ-law.
Live failed for account reasons: Azure Neural HD (region) and Groq (terms acceptance).
No key: Google, Rime, Inworld, Fish Audio, MiniMax, Murf, xAI, Smallest, Together. Polly: mock-only by decision.
