# Other notable TTS APIs (self-serve pricing)
Checked 2026-10-13 via vendor pages/search results; verify before building.

- **Mistral Voxtral TTS**: `POST https://api.mistral.ai/v1/audio/speech`, model `voxtral-mini-tts-2603` (alias `voxtral-mini-tts-latest`), $16 per 1M chars (intro pricing), streaming ~90 ms TTFA, 9 languages, cloning. https://docs.mistral.ai/models/voxtral-tts-26-03
- **xAI Grok TTS**: `/v1/tts` on `https://api.x.ai/v1` (full path inferred, UNVERIFIED), $15 per 1M input chars, REST and WebSocket, mp3/wav/pcm/mulaw/alaw, 50 rps. https://docs.x.ai/developers/models/text-to-speech
- **Smallest.ai Lightning v3.1 / v3.1 Pro**: `POST https://api.smallest.ai/waves/v1/tts`, SSE/WS `.../tts/live`, model `lightning_v3.1_pro`; about $17.50 (v3.1) and $19.50 (Pro) per 1M chars; pcm/mp3/wav/ulaw/alaw, 8/16/24/44.1 kHz. https://smallest.ai/pricing/models
- **Unreal Speech**: `/stream` (<=1000 chars), `/speech`, `/synthesisTasks` on api.v8.unrealspeech.com (host UNVERIFIED); plans $49/mo 3M chars (overage $16/1M) down to $8/1M at $4,999/mo; free 250K. https://unrealspeech.com/pricing
- **Sarvam Bulbul (Indian languages)**: V3 INR 30 per 10K chars, V4 Flash INR 20 per 10K chars, endpoint not verified. https://docs.sarvam.ai/api/getting-started/pricing
- **Neuphonic**: SSE `POST https://api.neuphonic.com/sse/speak/en` (`X-API-KEY`), WS `wss://api.neuphonic.com/speak/en`, voices `GET /voices`; price UNVERIFIED (no public page found). https://docs.neuphonic.com
- **Kokoro hosts**: not researched (UNVERIFIED).
