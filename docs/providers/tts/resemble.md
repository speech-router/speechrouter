# Resemble AI TTS

## Status
- Live. No deprecation found. "Resemble Ultra" is the default model for new/upgraded voices; model is chosen by the voice. https://docs.resemble.ai/voice-generation/text-to-speech
- WebSocket streaming requires Business plan or above. Streaming hosts are dedicated (dashboard shows your streaming endpoint); do not send to `app.resemble.ai`.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://f.cluster.resemble.ai/stream` https://docs.resemble.ai/voice-generation/text-to-speech/streaming-http
- Auth: `Authorization: Bearer <API_TOKEN>`; `Content-Type: application/json`.
- Body: `voice_uuid` (req), `data` (req, text or SSML, max 2000 chars), `precision` (`PCM_32` default, `PCM_24`, `PCM_16`, `MULAW`), `sample_rate` (8000, 16000, 22050, 32000, 44100, 48000 default), `use_hd` (bool), `project_uuid`, `apply_custom_pronunciations`. No speed/language/style fields (use SSML).
- Response: chunked single-channel PCM WAV stream (raw bytes). First bytes are WAV metadata (cue/list/ltxt chunks with grapheme/phoneme timestamps) before audio; audio in `data` chunk as PCM16. Docs inconsistency: default `PCM_32` vs header 16-bit; use `PCM_16` explicitly (UNVERIFIED real bit depth of other values).
```
curl --output out.wav "https://f.cluster.resemble.ai/stream" -H "Authorization: Bearer $RESEMBLE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"voice_uuid":"<VOICE_UUID>","data":"Hello there.","precision":"PCM_16","sample_rate":24000}'
```
- Sync alternative: `POST https://f.cluster.resemble.ai/synthesize` returns JSON with base64 `audio_content`, `duration`, `output_format` (`wav`/`mp3`). https://docs.resemble.ai/voice-generation/text-to-speech/synchronous

## Output formats
- HTTP stream: WAV only; `precision` enum `PCM_16`, `PCM_24`, `PCM_32`, `MULAW` (mulaw within WAV). `sample_rate` enum above.
- Sync: `output_format` `wav` or `mp3`. WS: `output_format` `wav`/`mp3`, `no_audio_header` for raw PCM, `sample_rate` 8000/16000/22050/32000/44100.
- opus/ogg and alaw: not offered.

## Models
- No model id parameter; model is derived from `voice_uuid`. "Resemble Ultra" is default for new voices. `use_hd` toggles HD. Other model names (e.g. Chatterbox) not in API docs: UNVERIFIED for API.

## Voices
- Identified by `voice_uuid`. List: `GET https://app.resemble.ai/api/v2/voices` (filter `pre_built_resemble_voice=true` for premade; fields `uuid`, `name`, `supported_languages`). https://docs.resemble.ai/voice-creation/voices/list
- Premade uuids: none listed in docs (UNVERIFIED; must be fetched via list). Default: none. Custom voices/cloning: yes.

## WebSocket / input streaming
- `wss://websocket.cluster.resemble.ai/stream` (Business plan+). Send JSON `{voice_uuid, data, request_id, output_format, sample_rate, precision, binary_response, no_audio_header}`; receive `audio` JSON frames with base64 `audio_content` + timestamps, or binary frames, then `audio_end`. Incremental-text (append) semantics: UNVERIFIED. https://docs.resemble.ai/guides/creating-clips/websocket-streaming/receiving-audio

## Usage reporting
- Sync response has `duration` and `synth_duration` (seconds); which is billed: UNVERIFIED. HTTP stream has no usage body.

## Pricing (list price, pay-as-you-go/API)
- UNVERIFIED: official pricing page (https://www.resemble.ai/pricing, checked 2026-10-13) lists only Detect/Intelligence/Identity/Watermarker rates; no TTS rate. Flex is pay-as-you-go credits (no subscription).
- Non-authoritative hint: vendor blog posts quote $0.030 per minute pay-as-you-go (one also writes "~$3/min"); do not rely on it. Billing appears time-based (seconds) rather than per character.

## Errors
- REST body: `{"success": false, "message": "..."}`; 400 body may include `success`, `error`, `errors` (map), `message`. Specific status code table not on the page (UNVERIFIED). https://docs.resemble.ai/getting-started/errors
- WS: synthesis errors recoverable, connection failures not.
