# Telnyx TTS

## Status
- Live. Voice ids are `Provider.Model.VoiceId` (or `Provider.VoiceId`). https://developers.telnyx.com/docs/voice/tts/rest-api/parameters

## HTTP endpoint
- `POST https://api.telnyx.com/v2/text-to-speech/speech`, `Authorization: Bearer $TELNYX_API_KEY`, JSON body.
- Body: `text` (req; markdown stripped), `voice` (req; e.g. `Telnyx.NaturalHD.astra`, `Telnyx.Ultra.aura`, `Telnyx.KokoroTTS.af`), `output_type` (`binary_output` default | `base64_output` | `audio_id`), `language` (providers that support it: AWS Polly, Azure, ElevenLabs, Inworld, Soniox; others ignore), `text_type` (`text`|`ssml`; Polly, Azure), `voice_settings` (object, provider-specific: speed/pitch/format/emotion), `pronunciation_dict_id`, `disable_cache`. No `model` or `output_format` field (a Telnyx code-examples PR reports they are not part of this endpoint; bare `nova` gave 422, `Telnyx.KokoroTTS.af_nova` gave 200 audio/mpeg).
- Response: `binary_output` raw bytes chunk-streamed (HTTP chunked; connection closes after 30 s without new chunks), `Content-Type` e.g. `audio/mpeg`; `base64_output` -> `{"base64_audio":"<b64>"}`; `audio_id` -> id for `GET /v2/text-to-speech/speech/:audio_id`. https://developers.telnyx.com/docs/voice/tts/rest-api
- Default container is MP3 (per examples). Sample rate on REST: UNVERIFIED; voice_settings `format` options UNVERIFIED.

## WebSocket
- `wss://api.telnyx.com/v2/text-to-speech/speech?voice=<voice_id>[&inactivity_timeout=20]`, `Authorization: Bearer` header.
- Send `{"text":" "}` to init, then `{"text":"..."}` any number of times, then `{"text":""}` to finish.
- Receive JSON with base64 `audio` (and `isFinal` per Hermes plugin README, third-party); audio is MP3 16 kHz 16-bit mono, each chunk a full MP3 (concatenate). Server closes when done. Cancel: no cancel message documented; close socket (UNVERIFIED). https://developers.telnyx.com/docs/voice/programmable-voice/tts-standalone

## Models / tiers
- Telnyx-hosted families seen: `Telnyx.KokoroTTS`, `Telnyx.Natural`, `Telnyx.NaturalHD`, `Telnyx.Ultra`; also third-party providers via same id scheme (`Polly.Amy-Neural` in call-control; `aws.Polly.Neural.Joanna` on REST page; `Azure...`, `Minimax.speech-2.8-turbo...`, `Inworld.Mini...`). The two Polly spellings conflict between pages; which is right for REST is UNVERIFIED.
- Kokoro: model = `KokoroTTS` family; underlying `hexgrad/Kokoro-82M` is UNVERIFIED.

## Voices
- Full catalog: `GET /v2/text-to-speech/voices` (needs key). Examples: Kokoro `Telnyx.KokoroTTS.af` (docs), `af_alloy`, `af_bella`, `am_adam`, `am_michael`, `ff_siwis` (fr), `pf_dora` (pt-BR); NaturalHD `astra` (plugin default), `luna`, `orion`, `celeste`, `bond`, `andromeda`, `iris`; Natural `abbie`; Ultra `aura`, `Clara`. Voice names for NaturalHD/Ultra from third-party plugins are UNVERIFIED.
- Default voice: none on the REST API (required).

## Formats & rates
- Mu-law 8 kHz: not documented for the standalone TTS API (UNVERIFIED). WS is MP3 16 kHz. Call-control speak action (separate) plays into calls natively.

## Usage reporting
- No billed-characters header documented. UNVERIFIED.

## Pricing https://telnyx.com/pricing/text-to-speech , checked 2026-10-13 (unit: per character; per 1K = x1000)
- Telnyx TTS $0.000003/char ($0.003/1K); Standard TTS (Amazon Polly) $0.000009; Telnyx HD Voices TTS $0.000048; Neural Voices TTS (Polly) $0.000024; MiniMax speech-2.8-turbo $0.000034; Rime $0.00002; Inworld Mini $0.0000055; Inworld Max $0.00001; Qwen3TTS $0.000032; Telnyx Ultra $0.000032; Resemble $0.000008; Murf $0.000008; ElevenLabs and Azure Neural HD: BYO key.
- The page does NOT name Kokoro, Natural or NaturalHD. Likely mapping Kokoro = "Telnyx TTS" $0.000003 and NaturalHD = "Telnyx HD Voices" $0.000048: UNVERIFIED inference.

## Limits
- Text length limit, rate limits: UNVERIFIED (page sections not retrievable). 30 s inter-chunk timeout on REST; WS inactivity default 20 s.

## Errors
- 422 on invalid voice id format (reported by third party PR). Error body shape UNVERIFIED.
