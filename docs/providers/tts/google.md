# Google Cloud Text-to-Speech (REST v1)

## Status
- Live (GA). Chirp 3: HD listed as "latest"; WaveNet, Studio, Standard, Neural2 labelled "Legacy TTS models" on pricing (https://cloud.google.com/text-to-speech/pricing, checked 2026-10-13). No shutdown found.
- Gemini-TTS on Cloud TTS: `gemini-2.5-flash-tts`, `gemini-2.5-pro-tts` (GA per listing), `gemini-3.1-flash-tts-preview`, `gemini-2.5-flash-lite-preview-tts` (Preview). Gemini 3.8 Flash/Flash-Lite TTS are Preview via Gemini Enterprise API only, not the Cloud TTS API. https://docs.cloud.google.com/text-to-speech/docs/gemini-tts

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- REST has NO streaming method: only unary `POST https://texttospeech.googleapis.com/v1/text:synthesize` (https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize). Streaming is `StreamingSynthesize` via client libs (gRPC; REST route not documented) -> UNVERIFIED for HTTP.
- Auth: documented: `Authorization: Bearer <OAuth token>` (scope `https://www.googleapis.com/auth/cloud-platform`), optionally `x-goog-user-project: PROJECT_ID`. API key support (`X-Goog-Api-Key` / `?key=`) is NOT mentioned in any TTS doc read -> UNVERIFIED.
- Body (JSON): `input` {`text` | `ssml` | `markup`, optional `prompt` for Gemini}, `voice` {`languageCode` (required, e.g. `en-US`), `name`, `ssmlGender`, `customVoice`{model}, Gemini: `model_name`/`modelName` (page inconsistent)}, `audioConfig` {`audioEncoding` (required), `speakingRate` 0.25-2.0 (default 1.0), `pitch` -20..20 (not for Chirp 3 HD, UNVERIFIED), `volumeGainDb`, `sampleRateHertz`, `effectsProfileId`}, optional `advancedVoiceOptions.lowLatencyJourneySynthesis`.
- Response: single JSON `{"audioContent": "<base64>"}` after full synthesis; container header included for LINEAR16 (WAV), MP3, OGG_OPUS (docs). Not chunked audio.
- Limits: 5,000 bytes per request (quotas page https://docs.cloud.google.com/text-to-speech/quotas); Gemini: text and prompt 4,000 bytes each, 8,000 combined, ~655 s audio.
- Example:
  ```
  curl -X POST "https://texttospeech.googleapis.com/v1/text:synthesize" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "x-goog-user-project: $PROJECT" -H "Content-Type: application/json; charset=utf-8" \
    -d '{"input":{"text":"Hello"},"voice":{"languageCode":"en-US","name":"en-US-Chirp3-HD-Kore"},"audioConfig":{"audioEncoding":"PCM","sampleRateHertz":24000}}'
  ```

## Output formats
`audioEncoding` enum (https://docs.cloud.google.com/text-to-speech/docs/reference/rest/Shared.Types/AudioEncoding):
- `LINEAR16` (16-bit s16le PCM WITH WAV header), `PCM` (same, headerless), `MP3` (32 kbps), `OGG_OPUS`, `MULAW` (WAV header), `ALAW` (WAV header), `M4A`.
- Rates: set `sampleRateHertz`; unsupported -> INVALID_ARGUMENT; native rate per voice via voices.list `naturalSampleRateHertz`. Gemini/Chirp 3 HD examples 24000 Hz; exact supported rate set UNVERIFIED. mulaw/alaw at 8000: set `sampleRateHertz: 8000` (supported rates UNVERIFIED).
- Chirp 3 HD: streaming = ALAW, MULAW, OGG_OPUS, PCM; batch = ALAW, MULAW, MP3, OGG_OPUS, PCM (default LINEAR16). Gemini unary: LINEAR16 (default), ALAW, MULAW, MP3, OGG_OPUS, PCM.

## Models / voice families
(https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types) tiers selected by the voice name; no separate model id except Gemini.
- Standard: `en-US-Standard-A`; WaveNet: `en-US-Wavenet-A`; Neural2: `en-US-Neural2-A`; Studio: `en-US-Studio-O`, `en-US-Studio-Q` (Studio multispeaker experimental); Polyglot, News, Casual naming also exist (examples UNVERIFIED).
- Chirp 3: HD: `<locale>-Chirp3-HD-<Name>`, e.g. `en-US-Chirp3-HD-Kore`; older Chirp HD: `en-US-Chirp-HD-D|F|O`.
- Gemini-TTS: voice `name` = bare star name (e.g. `Kore`) + model id above.
- Regions for Chirp 3 HD: global, us, eu, asia-southeast1, europe-west2, asia-northeast1 (regional endpoints UNVERIFIED format).

## Voices
- List: `GET https://texttospeech.googleapis.com/v1/voices?languageCode=en-US` -> `voices[]{languageCodes,name,ssmlGender,naturalSampleRateHertz}`.
- Chirp 3 HD 30 names (female: Achernar, Aoede, Autonoe, Callirrhoe, Despina, Erinome, Gacrux, Kore, Laomedeia, Leda, Pulcherrima, Sulafat, Vindemiatrix, Zephyr; male: Achird, Algenib, Algieba, Alnilam, Charon, Enceladus, Fenrir, Iapetus, Orus, Puck, Rasalgethi, Sadachbia, Sadaltager, Schedar, Umbriel, Zubenelgenubi). Gemini uses the same 30.
- en-US picks: `en-US-Chirp3-HD-Kore`, `en-US-Chirp3-HD-Charon`, `en-US-Chirp3-HD-Puck`, `en-US-Chirp3-HD-Aoede`, `en-US-Chirp3-HD-Fenrir`, `en-US-Chirp3-HD-Leda`, `en-US-Chirp3-HD-Achernar`, `en-US-Neural2-A`, `en-US-Neural2-C`, `en-US-Studio-O`, `en-US-Studio-Q`, `en-US-Wavenet-A`, `en-US-Standard-A`, `en-US-Chirp-HD-D`, `en-US-Chirp-HD-F`.
- Default suggestion: `en-US-Chirp3-HD-Kore` (cost: Neural2 `en-US-Neural2-C` cheaper).
- Custom voices: `voice.customVoice.model` (AutoML/custom model); Chirp instant custom voice/voice cloning exists in quotas ("Chirp voice cloning") - request shape UNVERIFIED.

## WebSocket / input streaming
- `StreamingSynthesize` (Chirp 3 HD, Gemini-TTS): bidirectional, first message config, later messages text chunks; client libs (gRPC). SSML not supported when streaming; Gemini `prompt` in first chunk and synthesis starts after client half-close. No WebSocket. Concurrent streaming sessions quota 100.

## Usage reporting
- Response contains only `audioContent`; no billed-character/token field documented.

## Pricing (list price, pay-as-you-go)
Source: https://cloud.google.com/text-to-speech/pricing, checked 2026-10-13 (figures obtained via search-tool summary of that page; page body itself did not render in fetch) 
- Per 1M characters: Standard $4 (free 4M/mo); WaveNet $4 (free 4M/mo; SKU shown same as Standard - page ambiguity); Neural2 $16 (free 1M); Studio $160 (free 1M); Chirp 3: HD $30 (free 1M). Polyglot, News/Casual, Chirp instant custom voice: UNVERIFIED.
- Gemini-TTS per 1M tokens (input text / output audio, 25 audio tokens per second): 2.5 Flash TTS and 2.5 Flash-Lite Preview TTS $0.50 / $10.00; 2.5 Pro TTS $1.00 / $20.00; 3.1 Flash TTS Preview $1.00 / $20.00. No free tier.
- Billing: characters of input incl. spaces/newlines; SSML tags (except `mark`) count; Standard/WaveNet multi-byte chars count as 1 character.

## Credentials
- Service account / ADC OAuth access token (cloud-platform scope) with the Text-to-Speech API enabled and billing on; optional `x-goog-user-project`. API key: UNVERIFIED for TTS in docs (Google APIs generally accept `?key=` but not confirmed here).

## Errors
- Standard Google API JSON error `{"error":{"code","message","status"}}` (e.g. INVALID_ARGUMENT for bad sample rate, speakingRate out of range) - shape from general Google API convention; TTS-specific code table UNVERIFIED (quotas page documents no error codes).
