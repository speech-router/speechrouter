# Azure AI Speech - TTS (REST)

## Status
- Live (GA). Docs updated 2026-05/06: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech
- Doc tip: REST use cases are "limited"; Microsoft recommends the Speech SDK where possible. No deprecation notice found for the REST endpoint.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1` (e.g. `eastus`; Gov: `https://usgovvirginia.tts.speech.azure.us/cognitiveservices/v1`). Resource-subdomain form `https://{name}.cognitiveservices.azure.com/cognitiveservices/v1` also shown in docs samples.
- Auth: `Ocp-Apim-Subscription-Key: <key>` OR `Authorization: Bearer <token>` (STS token from `POST https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken`, valid 10 min; Entra: `aad#<resourceId>#<entraToken>`).
- Required headers: `Content-Type: application/ssml+xml`, `X-Microsoft-OutputFormat: <format>`, `User-Agent: <app, <255 chars>`.
- Body: SSML. Voice and language are chosen in SSML; rate via `<prosody rate="...">` (NOT supported by DragonHD voices; supported on regular Neural voices).
- Minimal SSML:
  `<speak version='1.0' xml:lang='en-US'><voice xml:lang='en-US' name='en-US-AvaMultilingualNeural'>Hello</voice></speak>`
  (docs sample uses `en-US-ChristopherNeural` with `xml:gender='Male'`.)
- Response: HTTP 200, body is raw audio bytes in the requested format; "can be played as it is transferred" (chunked transfer for streaming formats). Not JSON/SSE. Audio capped at 10 min (truncated).
- Example:
  ```
  curl -X POST "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1" \
    -H "Ocp-Apim-Subscription-Key: $AZURE_SPEECH_KEY" \
    -H "Content-Type: application/ssml+xml" \
    -H "X-Microsoft-OutputFormat: raw-24khz-16bit-mono-pcm" \
    -H "User-Agent: gateway" \
    -d "<speak version='1.0' xml:lang='en-US'><voice name='en-US-AvaMultilingualNeural'>Hello</voice></speak>" -o out.pcm
  ```
- Custom voice: `https://{region}.voice.speech.microsoft.com/cognitiveservices/v1?deploymentId={id}` (body may be plain text).

## Output formats
Header `X-Microsoft-OutputFormat`; doc groups "Streaming" vs "NonStreaming" (https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech#audio-outputs).
- Raw PCM s16le mono (headerless): `raw-8khz-16bit-mono-pcm`, `raw-16khz-16bit-mono-pcm`, `raw-22050hz-16bit-mono-pcm`, `raw-24khz-16bit-mono-pcm`, `raw-44100hz-16bit-mono-pcm`, `raw-48khz-16bit-mono-pcm`
- WAV (non-streaming): `riff-8khz-16bit-mono-pcm`, `riff-22050hz-16bit-mono-pcm`, `riff-24khz-16bit-mono-pcm`, `riff-44100hz-16bit-mono-pcm`, `riff-48khz-16bit-mono-pcm` (note: no `riff-16khz` in the list)
- MP3: `audio-16khz-32kbitrate-mono-mp3`, `audio-16khz-64kbitrate-mono-mp3`, `audio-16khz-128kbitrate-mono-mp3`, `audio-24khz-48kbitrate-mono-mp3`, `audio-24khz-96kbitrate-mono-mp3`, `audio-24khz-160kbitrate-mono-mp3`, `audio-48khz-96kbitrate-mono-mp3`, `audio-48khz-192kbitrate-mono-mp3`
- Opus: `ogg-16khz-16bit-mono-opus`, `ogg-24khz-16bit-mono-opus`, `ogg-48khz-16bit-mono-opus`, `webm-16khz-16bit-mono-opus`, `webm-24khz-16bit-mono-opus`, `webm-24khz-16bit-24kbps-mono-opus`, `audio-16khz-16bit-32kbps-mono-opus`, `audio-24khz-16bit-24kbps-mono-opus`, `audio-24khz-16bit-48kbps-mono-opus`
- mulaw/alaw 8 kHz: raw `raw-8khz-8bit-mono-mulaw`, `raw-8khz-8bit-mono-alaw`; WAV `riff-8khz-8bit-mono-mulaw`, `riff-8khz-8bit-mono-alaw`
- Others: `amr-wb-16000hz`, `g722-16khz-64kbps`, `raw-16khz-16bit-mono-truesilk`, `raw-24khz-16bit-mono-truesilk`
- Voices are natively 24 kHz or 48 kHz; other rates are resampled (48 kHz format invokes the hi-fi model).

## Models / voice families
- Neural (standard): ids end `Neural`, e.g. `en-US-JennyNeural`, `en-US-AvaMultilingualNeural` (VoiceType "Neural").
- Dragon HD: `{locale}-{Name}:DragonHDLatestNeural` (e.g. `en-US-Ava:DragonHDLatestNeural`); ~30 voices; limited SSML (no prosody/break differences: break/phoneme yes, prosody no); real-time only.
- Dragon HD Omni: `{locale}-{name}:DragonHDOmniLatestNeural` (700+ voices, `mstts:express-as` styles, multilingual).
- Dragon HD Flash: `{locale}-{Name}:DragonHDFlashLatestNeural` (en-US: Tiana, Tyler, Jimmie; plus zh-CN); regions eastus, westeurope, southeastasia (+chinanorth3).
- Optional `parameters='temperature=0.8'` on `<voice>` for HD.
- Source: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/high-definition-voices
- MAI-Voice appears as a pricing line item (https://azure.microsoft.com/en-us/pricing/details/speech/); model ids/naming UNVERIFIED.
- Azure OpenAI voices via Speech: UNVERIFIED ids in this research.

## Voices
- Naming: `{locale}-{Name}Neural` (ShortName) or `{locale}-{Name}:{DragonHD...}`.
- List: `GET https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list` (also `https://{name}.cognitiveservices.azure.com/tts/cognitiveservices/voices/list`) with key header; returns JSON with Name, ShortName, Gender, Locale, StyleList, SampleRateHertz, VoiceType, Status, WordsPerMinute.
- en-US verified in docs: `en-US-JennyNeural`, `en-US-JennyMultilingualNeural`, `en-US-ChristopherNeural`, `en-US-Ava:DragonHDLatestNeural`, `en-US-Andrew:DragonHDLatestNeural`, `en-US-Andrew2:DragonHDLatestNeural`, `en-US-Emma:DragonHDLatestNeural`, `en-US-Emma2:DragonHDLatestNeural`, `en-US-Brian:DragonHDLatestNeural`, `en-US-Aria:DragonHDLatestNeural`, `en-US-Davis:DragonHDLatestNeural`, `en-US-Jenny:DragonHDLatestNeural`, `en-US-Nova:DragonHDLatestNeural`, `en-US-Phoebe:DragonHDLatestNeural`, `en-US-Serena:DragonHDLatestNeural`.
- `en-US-AvaMultilingualNeural` exact existence: UNVERIFIED in the pages read (use the voices list); safe verified default: `en-US-JennyNeural` (non-HD) .
- Suggested default: `en-US-JennyNeural` (verified in docs sample list; confirm availability in region via voices/list).
- Custom voices: yes (Professional Voice, deployment endpoint above; Personal Voice via speakerProfileId).

## WebSocket / input streaming
- Docs for the REST page describe no WebSocket; the Speech SDK uses an internal websocket (text-streaming APIs in SDK) - UNVERIFIED in the pages read.
- Gateway should use REST chunked response (text-in once, audio streamed out).

## Usage reporting
- Response is raw audio only; no billed-character field. (Count client-side.)

## Pricing (list price, pay-as-you-go)
- Official page https://azure.microsoft.com/en-us/pricing/details/speech/ rendered all prices as "$-" when fetched 2026-10-13 -> exact $/1M chars for Neural, Neural HD, HD Flash, MAI-Voice: UNVERIFIED.
- Verified: line items are per 1M characters (Neural/Neural HD Flash share a row; Neural HD; MAI-Voice; Custom Professional); free F0 tier: 0.5M Neural characters/month.
- Third-party (Microsoft Q&A, older posts, not authoritative): Neural ~ $16/1M. Treat as UNVERIFIED.
- Billing unit: "billed per character". Whether SSML markup counts: UNVERIFIED on the page (Microsoft Q&A: https://learn.microsoft.com/en-us/answers/questions/233277 discusses it; not read).
- Checked 2026-10-13.

## Credentials
- Speech resource key + region (key header works with all endpoint formats), or Entra/bearer token. Use region-matched endpoint.

## Errors
- 400 bad request (missing/invalid param, header too long), 401 unauthorized (bad key/token/region), 415 wrong Content-Type (must be `application/ssml+xml`), 429 quota/rate, 502 bad gateway/invalid headers, 503 unavailable.
- Error body shape: UNVERIFIED (not documented on the page).
