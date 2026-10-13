# Mistral Voxtral TTS

## Status
- Live; Voxtral TTS v26.03, released 2026-03-23. Model page license shows CC BY-NC 4.0 (open weights; API terms separate, UNVERIFIED). https://docs.mistral.ai/models/voxtral-tts-26-03

## HTTP endpoint
- `POST https://api.mistral.ai/v1/audio/speech`, `Content-Type: application/json`. https://docs.mistral.ai/api/endpoint/audio/speech
- Auth: `Authorization: Bearer $MISTRAL_API_KEY` (UNVERIFIED on the TTS page; consistent with the example curl).
- Body: `input` (string, required), `model` (string|null), `voice_id` (string|null; preset slug or custom voice UUID; NOT `voice`), `ref_audio` (string|null; base64 reference clip for one-off cloning), `response_format` (`pcm|wav|mp3|flac|opus`), `stream` (bool, default false), `phoneme_hints` (map word -> ordered IPA phone list), `metadata` (map), `prompt_cache_key` (string|null). No speed, sample_rate or language fields documented; language follows text/voice prompt.
- Response, `stream:false`: `application/json` `{"audio_data":"<base64>"}`.
- Response, `stream:true`: `text/event-stream`, typed `SpeechStreamEvents` (API ref gives no field list). Third-party report (PR in wuan/voxoracle checking the OpenAPI spec, plus Mistral cookbook `sts_demo.py` per search summary): delta events `event: speech.audio.delta` with `data: {"type":"speech.audio.delta","audio_data":"<base64>"}` and a terminal `speech.audio.done`. The done event payload (usage?) is UNVERIFIED. Event names and exact JSON are UNVERIFIED against Mistral's own docs; verify with a live call.
- pcm is "Raw float32 LE samples, recommended for streaming (lowest latency)" (https://docs.mistral.ai/studio/audio/text_to_speech/speech). Sample rate not published in docs; Pipecat docs say native output is 24 kHz (third party, UNVERIFIED officially).

## WebSocket
- None documented (Pipecat notes streaming uses HTTP SSE). UNVERIFIED beyond that.

## Models
- `voxtral-mini-tts-2603` (confirmed). `voxtral-mini-tts-latest` alias: UNVERIFIED (model page shows "+1" hidden alias).

## Voices
- Preset voices identified by slug (e.g. `fr_marie_neutral`) or UUID; list with `/v1/audio/voices` (fields `slug`, `id`), per Pipecat docs. The full preset list is UNVERIFIED (docs page not retrievable). Custom voices: create via Voices API (`name`, `sample_audio` base64, optional `slug`, `languages`, `gender`, `age`, `tags`).
- Default voice: none (Pipecat default None). 9 languages: English, French, Spanish, Portuguese, Italian, Dutch, German, Hindi, Arabic.

## Formats & rates
- `response_format`: `pcm` (float32 LE), `wav` (uncompressed PCM), `mp3`, `flac`, `opus`. No mulaw/alaw: 8 kHz mu-law NOT native; transcode client-side. Native 24 kHz: UNVERIFIED.
- Latency (docs): ~90 ms model time; end-to-end TTFA ~0.8 s for pcm, ~3 s for mp3.

## Usage reporting
- Not documented in response (only `audio_data`). UNVERIFIED for headers or done-event usage.

## Pricing
- $16 per 1M characters for voxtral-mini-tts-2603 (model page shows "$16 /M Chars", also a "$0" lower bound with no explanation). "Introductory" label: UNVERIFIED. Unit: input characters. Source https://docs.mistral.ai/models/voxtral-tts-26-03 , checked 2026-10-13.

## Limits
- Prompts under 300 words recommended "for best results"; hard limits UNVERIFIED. Certain text is rejected with 403 (moderation). Rate limits UNVERIFIED.

## Errors
- 403 moderation rejection documented; standard Mistral error JSON otherwise (UNVERIFIED shape).
