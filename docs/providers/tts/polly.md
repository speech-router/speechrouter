# AWS Polly TTS

## Status
- Live. Engines: `standard`, `neural`, `long-form`, `generative`. https://docs.aws.amazon.com/polly/latest/dg/API_SynthesizeSpeech.html

## HTTP endpoint (SynthesizeSpeech)
- `POST https://polly.{region}.amazonaws.com/v1/speech` (request path `/v1/speech`, no URI params; host form UNVERIFIED from the page itself, which shows only the path).
- Auth: AWS SigV4. Signing service name `polly`: UNVERIFIED this session (not stated on the fetched page).
- Body (JSON, PascalCase): `Engine` (`standard|neural|long-form|generative`, default `standard`), `LanguageCode` (only needed for bilingual voices, e.g. `en-US`, `en-GB`), `LexiconNames` (array, max 5), `OutputFormat` (required; `json|mp3|ogg_opus|ogg_vorbis|pcm|mulaw|alaw`), `SampleRate` (STRING, e.g. `"8000"`), `SpeechMarkTypes` (array max 4: `sentence|ssml|viseme|word`), `Text` (required), `TextType` (`ssml|text`, default text), `VoiceId` (required).
- No speed field; use SSML `<prosody rate=...>` (SSML tag support per engine UNVERIFIED).
- Response: HTTP 200, raw audio bytes (chunked body), `Content-Type` per format: mp3 `audio/mpeg`, ogg_vorbis/ogg_opus `audio/ogg`, pcm `audio/pcm`, mulaw `audio/mulaw`, alaw `audio/alaw`, json `application/x-json-stream`. Not SSE, not base64.
- pcm is signed 16-bit, mono, little-endian.
```
POST /v1/speech
{"Engine":"generative","OutputFormat":"pcm","SampleRate":"16000","Text":"Hello","TextType":"text","VoiceId":"Joanna","LanguageCode":"en-US"}
```

## Streaming / WebSocket
- No WebSocket. `StartSpeechSynthesisStream`: `POST /v1/synthesisStream`, HTTP/2 bidirectional event stream. Parameters go in headers `x-amzn-Engine`, `x-amzn-VoiceId`, `x-amzn-OutputFormat`, `x-amzn-SampleRate`, `x-amzn-LanguageCode`, `x-amzn-LexiconNames`. Docs say currently only `generative` engine is supported. https://docs.aws.amazon.com/polly/latest/dg/API_StartSpeechSynthesisStream.html
- Input events: `TextEvent` {`Text`, `TextType`, `FlushStreamConfiguration`:{`Force`}} and `CloseStreamEvent`. Output events: `AudioEvent`{`AudioChunk`: blob}, `StreamClosedEvent`{`RequestCharacters`}, plus exception events.
- Cancel: no explicit cancel event documented; close the HTTP/2 stream (UNVERIFIED behavior). Also AWS SDK event-stream signing required (UNVERIFIED details).

## Models (engines)
`standard`, `neural`, `long-form`, `generative`. Default if omitted: `standard` (errors if voice lacks standard).

## Voices (en-US, from https://docs.aws.amazon.com/polly/latest/dg/available-voices.html)
| VoiceId | Gender | generative | long-form | neural | standard |
|---|---|---|---|---|---|
| Danielle | F | yes | yes | yes | no |
| Gregory | M | no | yes | yes | no |
| Ivy | F child | no | no | yes | yes |
| Joanna | F | yes | no | yes | yes |
| Kendra | F | no | no | yes | yes |
| Kimberly | F | no | no | yes | yes |
| Salli | F | yes | no | yes | yes |
| Joey | M | no | no | yes | yes |
| Justin | M child | no | no | yes | no |
| Kevin | M child | no | no | yes | yes |
| Matthew | M | yes | no | yes | no |
| Ruth | F | yes | yes | yes | no |
| Stephen | M | yes | no | yes | no |
| Tiffany | F | yes | no | no | no |
| Patrick | M | no | yes | no | no |
- en-GB: Amy (generative yes, neural yes, standard yes), Emma (neural, standard), Brian (generative, neural, standard), Arthur (neural). Joanna and Matthew support Newscaster style with neural.
- Default voice: none (VoiceId required). Suggested: Joanna (generative/neural).
- Caveat: the fetched table is a rendering of the docs; Patrick/Tiffany/Gregory columns look unusual (Justin/Kevin shown as child voices) but are as published.

## Formats & rates
- `SampleRate` (string): mp3 and ogg_vorbis `"8000","16000","22050","24000","44100","48000"`; defaults standard `"22050"`, neural/long-form/generative `"24000"`. pcm: `"8000"` or `"16000"` (default `"16000"`; 24000 is NOT valid for pcm). ogg_opus: `"48000"`. mulaw and alaw: `"8000"`.
- 8 kHz mu-law is native-supported: `OutputFormat":"mulaw","SampleRate":"8000"`.
- Per-engine restrictions on rates beyond the above: UNVERIFIED.

## Usage reporting
- Response header `x-amzn-RequestCharacters`: number of characters synthesized (billed characters; SSML tags not counted). Streaming API: `StreamClosedEvent.RequestCharacters`.

## Pricing (per 1M characters, pay-as-you-go) https://aws.amazon.com/polly/pricing/ , checked 2026-10-13
- standard $4.00; neural $16.00; long-form $100.00; generative $30.00 (speech requests). Billing unit: characters of input (excl. SSML tags).
- Free tier: standard 5M chars/month (page text); neural 1M, long-form 500K, generative 100K per month for first 12 months.
- Region-specific price differences: UNVERIFIED.

## Limits
- SynthesizeSpeech: max 6000 characters total, of which at most 3000 billed. Async StartSpeechSynthesisTask: 200,000 total / 100,000 billed. `LexiconNames` max 5.
- TPS/concurrency quotas: UNVERIFIED.

## Errors
- 400: EngineNotSupportedException, InvalidSampleRateException, InvalidSsmlException, LanguageNotSupportedException, MarksNotSupportedForFormatException, SsmlMarksNotSupportedForTextTypeException, TextLengthExceededException. 404: LexiconNotFoundException. 500: ServiceFailureException. Streaming API adds ThrottlingException (400), ServiceQuotaExceededException (402), ValidationException (400).
