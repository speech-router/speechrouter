# Smallest.ai Lightning v3.1 TTS

## Status
- Live. Current docs use `/waves/v1/tts`; older per-model URL `.../waves/v1/lightning-v3.1/get_speech` is described by third parties and still in some samples (UNVERIFIED current). https://docs.smallest.ai/models/model-cards/text-to-speech/lightning-v-3-1

## HTTP endpoints
- Sync: `POST https://api.smallest.ai/waves/v1/tts` -> raw audio bytes (examples send `Accept: audio/wav`). https://docs.smallest.ai/waves/documentation/text-to-speech-lightning/quickstart
- SSE: `POST https://api.smallest.ai/waves/v1/tts/live` (`Content-Type: text/event-stream`).
- Auth: `Authorization: Bearer $SMALLEST_API_KEY` (access tokens not accepted).
- Body (same for both): `text` (req, max 8000 chars after trim; ~250 recommended per chunk), `voice_id` (req), `model` (`lightning_v3.1` default | `lightning_v3.1_pro`), `sample_rate` (int enum 8000|16000|24000|44100, default 44100), `speed` (float 0.5-2.0, default 1), `language` (code or `auto`, default `en`), `output_format` (`pcm` default | `wav` | `mp3` | `ulaw` | `alaw`), `pronunciation_dicts` (string list), `number_pronunciation_language`, `math_notation` (bool), `content_filter` {`enabled`,`action`:`reject|flag`}, `session_id`, `request_id` (max 128; echoed as `X-External-Session-Id` / `X-External-Request-Id`), `word_timestamps` (ignored on HTTP/SSE).
- Sync response: binary audio of `output_format`. Whether the sync body is chunk-streamed progressively: UNVERIFIED.
- SSE response frames (from https://docs.smallest.ai/api-reference/models/text-to-speech/synthesize-speech-sse.md):
```
event: audio
data: {"audio": "<base64-pcm>", "done": false, "status": "206"}

data: {"status": "200", "done": true}
```
Audio in SSE is described as base64 PCM; whether it honors `output_format` for other formats: UNVERIFIED.
```
curl -X POST https://api.smallest.ai/waves/v1/tts -H "Authorization: Bearer $SMALLEST_API_KEY" -H "Content-Type: application/json" -d '{"text":"Hello","voice_id":"magnus","sample_rate":8000,"output_format":"ulaw"}' --output out.ulaw
```
(exact combo ulaw+8000 not shown in docs; each is individually documented.)

## WebSocket
- `wss://api.smallest.ai/waves/v1/tts/live`, header `Authorization: Bearer <key>`.
- Send JSON {`voice_id`,`text`,`model`,`sample_rate`,`output_format`, optional `word_timestamps`, `context_id`, `pronunciation_dicts`}.
- Server frames carry `session_id`,`request_id`,`status`: `chunk` (`data.audio` base64), `word_timestamp` (`data`: id, word, start, end), `complete`. Cancel/flush message: UNVERIFIED (not in fetched pages).

## Models
- `lightning_v3.1` (217 voices, 12 trained languages, supports cloning), `lightning_v3.1_pro` (31 languages, curated pool, dedicated capacity). Pairing a Pro voice with the standard model produces bad audio and is not rejected.

## Voices
- List: `GET /waves/v1/lightning-v3.1/get_voices`. Standard-pool examples in docs: `meher`, `magnus`, `devansh`, `kartik`, `maithili`, `liam`, `avery`. Pro-pool ids (from v3.1 Pro card): `rhea`, `zariya`, `kareena`, `mishka`, `meher`, `aviraj`, `vyom` (Indian EN); `sophie`, `ellie`, `sam`, `henry` (UK); `kaitlyn`, `savannah`, `amelia`, `zoe`, `ruby`, `leah`, `jenna`, `kate`, `molly`, `sara`, `fiona`, `blake`, `austin`, `jack`, `leo`, `luke`, `owen` (US).
- Default voice: none (required). Which of the Pro ids exist on the standard pool: UNVERIFIED.

## Formats & rates
- Formats: PCM, WAV, MP3, `ulaw`, `alaw` (enum string is `ulaw`, not `mulaw`, in v3.1 docs; older v2/v3.0 docs use `mulaw`). Rates 8000/16000/24000/44100; native 44.1 kHz mono. 8 kHz mu-law supported via `sample_rate:8000` + `output_format:ulaw` (whether it's native or resampled: UNVERIFIED). PCM sample format (s16le assumed): UNVERIFIED.

## Usage reporting
- No billed-character header documented. Only echo headers above. UNVERIFIED otherwise.

## Pricing https://smallest.ai/pricing/models , checked 2026-10-13
- Lightning V3.1 ~$0.175 per 10K characters; V3.1 Pro ~$0.195 per 10K characters (pay-as-you-go; "~" as printed). Unit: characters. Enterprise custom.

## Limits
- text max 8000 chars (HTTP/SSE); max chunk 250 chars (~140 optimal); concurrency 10 on Standard plan (per Pro card); ~200 ms TTFB.

## Errors
- 400, 401, 500 with JSON `error` and `message`; content filter reject: 400 with `error_code:"CONTENT_FILTER_BLOCKED"`. 429 handling UNVERIFIED.
