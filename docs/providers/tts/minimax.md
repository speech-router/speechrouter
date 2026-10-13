# MiniMax T2A (speech-2.x)

## Status
- Live on the international platform (https://platform.minimax.io/docs/api-reference/speech-t2a-http). Checked 2026-10-13.
- Current models are the 2.8 family. 2.6, 02 and 01 are listed as older ids and still accepted by the API reference. No deprecation notice was found (UNVERIFIED).
- No acquisition.

## HTTP streaming endpoint (the one to use for "send text, stream audio back")
- `POST https://api.minimax.io/v1/t2a_v2`.
- Auth: `Authorization: Bearer <API_KEY>`, plus `Content-Type: application/json`.
- GroupId: the current doc page does not mention it. The error table says code 1004 means "token doesn't match group". The legacy `?GroupId=` query param is UNVERIFIED. Try without it first.
- Body:
  - `model` (required).
  - `text` (required): under 10,000 chars. Streaming is recommended above 3,000. Supports pause markers `<#x#>` (x = 0.01-99.99 seconds). Interjection tags work on 2.8 models only.
  - `stream`: bool, default false.
  - `voice_setting`: `voice_id` (required), `speed` (0.5-2, default 1), `vol` ((0,10], default 1), `pitch` (-12 to 12), `emotion` (`happy`, `sad`, `angry`, `fearful`, `disgusted`, `surprised`, `calm`, `fluent`, `whisper`; `fluent` and `whisper` are 2.6 models only).
  - `audio_setting`: `format`, `sample_rate`, `bitrate` (MP3 only), `channel` (1 or 2), `force_cbr` (streamed MP3).
  - `language_boost`: e.g. `English`, `Chinese,Yue`, `Japanese`, or `auto`.
  - `output_format`: `hex` (default) or `url`, non-streaming only. URLs expire after 24 hours.
  - Also `subtitle_enable`, `subtitle_type`, `voice_modify`, `pronunciation_dict`, `timbre_weights`, `text_normalization_mode`.
- Response with `stream:true`: `text/event-stream` (SSE).
  - Each event is `data: {json}`. `data.audio` is HEX-encoded audio bytes, and `data.status` is 1 while generating and 2 on the final chunk.
  - The final chunk carries a summary `extra_info`. The exact placement of the status 2 chunk (it may repeat full audio) is UNVERIFIED, so handle it defensively.
  - Non-streaming returns one JSON object with `data.audio` as hex (or a url).
- Example body:
```json
{"model":"speech-2.8-turbo","text":"Hello from the gateway.","stream":true,
 "voice_setting":{"voice_id":"English_expressive_narrator","speed":1,"vol":1,"pitch":0},
 "audio_setting":{"format":"pcm","sample_rate":24000,"channel":1},
 "language_boost":"English"}
```

## Output formats
- `audio_setting.format` enum: `mp3` (default), `pcm`, `flac`, `wav`, `pcmu_raw`, `pcmu_wav`, `opus`.
  - `pcm` is raw s16le (header-less, assumed from the name).
  - `pcmu_raw` and `pcmu_wav` are mu-law (G.711 u-law).
- `sample_rate` enum: 8000, 16000, 22050, 24000, 32000, 44100.
- `bitrate`: 32000, 64000, 128000 or 256000, MP3 only.
- No alaw. Native model rate is UNVERIFIED. The doc's example uses 32000.

## Models
- `speech-2.8-hd`: highest quality, current HD tier. Supports interjection tags.
- `speech-2.8-turbo`: lower-latency, cheaper current tier.
- `speech-2.6-hd` and `speech-2.6-turbo`: previous generation. Adds the `fluent` and `whisper` emotions.
- `speech-02-hd` and `speech-02-turbo`: older.
- `speech-01-hd` and `speech-01-turbo`: oldest listed.
- Pricing page lists only 2.8, plus 2.6 and 02 as "legacy" (https://platform.minimax.io/docs/guides/pricing-paygo). Descriptions beyond hd/turbo are UNVERIFIED.

## Voices
- Identified by string `voice_id`. System voices plus clones (`voice_cloning`) and designed voices (`voice_generation`).
- List: `POST https://api.minimax.io/v1/get_voice` with body `{"voice_type":"system"|"voice_cloning"|"voice_generation"|"all"}` and Bearer auth. The response is `system_voice[{voice_id,voice_name,description[]}]`, plus `voice_cloning`, `voice_generation` and `base_resp` (https://platform.minimax.io/docs/api-reference/voice-management-get). Clones and designs are listed only after first successful synthesis.
- The system voice list changes over time. English ids as published (https://platform.minimax.io/docs/faq/system-voice-id), 45 total, 15 shown:
  - `English_expressive_narrator`: Expressive Narrator. **Default**, used in the doc example.
  - `English_radiant_girl`: Radiant Girl.
  - `English_magnetic_voiced_man`: Magnetic-voiced Male.
  - `English_compelling_lady1`: Compelling Lady.
  - `English_Aussie_Bloke`: Aussie Bloke.
  - `English_captivating_female1`: Captivating Female.
  - `English_Upbeat_Woman`: Upbeat Woman.
  - `English_Trustworth_Man`: Trustworthy Man.
  - `English_CalmWoman`: Calm Woman.
  - `English_Gentle-voiced_man`: Gentle-voiced Man.
  - `English_Graceful_Lady`: Graceful Lady.
  - `English_ManWithDeepVoice`: Man With Deep Voice.
  - `English_FriendlyPerson`: Friendly Guy.
  - `English_Wiselady`: Wise Lady.
  - `English_ConfidentWoman`: Confident Woman.
- Arbitrary ids: only system voices or ones you created. Error 2042 means no access to this `voice_id`, and 20132 means an invalid `voice_id`.

## WebSocket / input streaming
- `wss://api.minimax.io/ws/v1/t2a_v2` with `Authorization: Bearer` (https://platform.minimax.io/docs/api-reference/speech-t2a-websocket).
- Client events: `task_start` (needs `model` and `voice_setting`, optional `audio_setting`), then wait for `task_started`. Then `task_continue` (text, up to 10,000 chars each; the connection closes after 120 s idle), then `task_finish`.
- Server: `task_continued` messages with hex `data.audio`, and `is_final:true` on the last.

## Usage reporting
- Confirmed: the response `extra_info.usage_characters` is the billable character count for the request. `extra_info.word_count` is reference only and not billed.
- `extra_info` also has `audio_length` (ms), `audio_size` (bytes), `audio_sample_rate`, `bitrate`, `audio_format`, `audio_channel` and `invisible_character_ratio` (the request fails above 10%). `trace_id` is at the top level.
- Whether `usage_characters` appears on every SSE chunk or only the final one is UNVERIFIED.

## Pricing (list price, pay-as-you-go/API)
- Source: https://platform.minimax.io/docs/guides/pricing-paygo, checked 2026-10-13.
- Unit: per 1M characters.
  - `speech-2.8-hd`: $100 per 1M chars (sync and async).
  - `speech-2.8-turbo`: $60 per 1M chars (sync and async).
  - `speech-2.6-hd` and `speech-02-hd`: $100 per 1M chars.
  - `speech-2.6-turbo` and `speech-02-turbo`: $60 per 1M chars.
  - `speech-01-*`: UNVERIFIED.
- Voice management is billed separately: Voice Design $3 per voice, and Rapid Voice Cloning $1.50 per voice. Both are charged on first synthesis use. Design preview synthesis is $60 per 1M chars.
- How characters are counted (for example, whether CJK counts as 2) is NOT stated on the pricing page, so UNVERIFIED. Rely on `extra_info.usage_characters` to bill.

## Errors
- Application errors are in `base_resp.status_code` and `base_resp.status_msg`. `0` means success (https://platform.minimax.io/docs/api-reference/errorcode).
- Whether they arrive with HTTP 200 is NOT confirmed in the docs I fetched. The HTTP status behaviour is UNVERIFIED, so handle both, and always check `base_resp` first.
- Common codes: 1000 unknown, 1001 timeout, 1002 rate limit, 1004 auth failed (token does not match group), 1008 insufficient balance, 1024 internal error, 1026 and 1027 sensitive input or output, 1039 TPM limit, 1041 connection limit, 1042 more than 10% invalid characters, 2013 invalid parameters, 20132 invalid `voice_id`, 2042 no access to voice, 2045 rate growth limit, 2049 invalid API key, 2056 usage limit exceeded (5-hour window).
