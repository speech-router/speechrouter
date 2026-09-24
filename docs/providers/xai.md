# xAI (Grok Voice Transcribe) — STT protocol brief (docs read 2026-09-23)

Docs: docs.x.ai `/developers/model-capabilities/audio/speech-to-text` (guide; append `.md` for markdown), `/developers/rest-api-reference/inference/speech-to-text`, the machine-readable WS schema `https://docs.x.ai/stt-streaming.ws.json`, `/developers/models/speech-to-text`, `/developers/pricing`, `/developers/rate-limits`, announcement x.ai/news/grok-voice-transcribe-2 (2026-09-18). `/v1/stt` is **not** in `docs.x.ai/openapi.json` and `xai-sdk-python` has no STT module; the only official client is the Rust streaming client in `github.com/xai-org/grok-build` (`crates/codegen/xai-grok-voice/src/stt/`). **Not yet live-verified** beyond unauthenticated probes (see Errors); open questions under Open.

| Model | Status |
|---|---|
| `grok-voice-transcribe-2.0` | released 2026-09-18, "our best"; the one we list |
| `grok-voice-transcribe-1.0` | "Original model. Pin this slug to keep it"; "will be deprecated in the coming weeks" — not added |

| Endpoint | Auth |
|---|---|
| `wss://api.x.ai/v1/stt?<config>` | `Authorization: Bearer <key>` header on the upgrade |
| `POST https://api.x.ai/v1/stt` | `Authorization: Bearer <key>` |

**Not OpenAI-compatible**: `POST /v1/audio/transcriptions` is a 404 (probed). Field names and response shape are xAI's own (Deepgram-flavoured).

## Realtime WS
- Config is **query params only**, no setup message: `model` (default 2.0), `sample_rate` (16000 default; 8000/16000/22050/24000/44100/48000; ignored for opus), `encoding` (`pcm` = s16le default | `mulaw` | `alaw` | `opus`), `interim_results` (default **false**, ~every 500 ms), `endpointing` (ms, default **400**, 0–5000; 0 = any VAD boundary), `language` (enables ITN only), `diarize`, `filler_words` (default **false** = fillers removed), `multichannel` + `channels` (≤8, interleaved; not with opus), `keyterm` (repeat per term, **max 100, ≤50 chars**), `smart_turn` (0–1, ML end-of-turn), `smart_turn_timeout` (ms 1–5000), `vad_threshold` (default **0.08**; "does not affect endpointing or `speech_final` timing").
- A bad key is refused **before 101** with an HTTP status + JSON body. `?token=` is not accepted. Ephemeral tokens are documented only for `/v1/realtime` (speech-to-speech).
- Ready: server sends `{"type":"transcript.created","id":"..."}` — "**Wait for this event before sending audio**". xAI's client waits ≤10 s.
- Audio: raw **binary** frames, no base64; "real-time-paced chunks (e.g. 100 ms)". 16 kHz PCM is "the model's native rate". Opus = exactly one raw packet per frame, no container, mono.
- Client JSON: `{"type":"finalize"}` / `{"type":"Finalize"}` forces `speech_final` (session stays open); `{"type":"audio.done"}` = end of input → server flushes, sends `transcript.done` (one per channel), closes.
- Undocumented: keepalive frame, idle timeout (the error text mentions "stream timeouts"), max session length, close codes.

```
wss://api.x.ai/v1/stt?model=grok-voice-transcribe-2.0&sample_rate=16000&encoding=pcm&interim_results=true&language=en&keyterm=Understand+The+Universe
← {"type":"transcript.created","id":"83f2f6fd-1cd1-4747-bc52-cebddc961c32"}
```

## Server events
JSON text frames dispatched on `type`; xAI's client ignores unknown types.
```
{"type":"transcript.partial","text":"The balance is $167,983.15.","words":[{"text":"The","start":0.24,"end":0.48,"confidence":0.95},...],"is_final":true,"speech_final":false,"start":0.0,"duration":3.2}
{"type":"transcript.partial","text":"I will buy two of those, please.","words":[...],"is_final":true,"speech_final":true,"start":0.0,"duration":2.4,"end_of_turn_confidence":0.983}
{"type":"transcript.done","text":"","words":[],"duration":6.43}
{"type":"error","message":"Invalid message: expected {\"type\": \"audio.done\"}"}
```
- `transcript.partial`: `text, words, is_final, speech_final, start` ("seconds from stream start, 2 d.p."), `duration`; `channel_index` (multichannel), `end_of_turn_confidence` (smart_turn). `words[]` = `{text, start, end, confidence?, speaker?}` in seconds; confidence "omitted when 0"; `speaker` 0-based int with `diarize=true`.

| `is_final` | `speech_final` | Meaning (verbatim) |
|---|---|---|
| false | false | "Interim — text may change (only when `interim_results=true`)" |
| true | false | "Chunk final — text locked, ~3s of speech finalized" (smart_turn also demotes low-confidence pauses to this) |
| true | true | "Utterance final — speaker stopped, **complete stitched utterance**" |

- `transcript.done`: `text, words, duration` (+`channel_index`). "Connection closes after this event."
- `error`: `{type, message}`, no code. "Most errors (pipeline failures, stream timeouts, undecodable audio frames) close the connection. Only client message parse errors keep the connection open."

## Batch
- `POST /v1/stt`, multipart. **Option fields before `file`** ("fields sent after `file` may be ignored"). Booleans as `"true"`/`"false"`.
- Fields: `file` | `url`, `model`, `audio_format` (raw only: `pcm`|`mulaw`|`alaw`), `sample_rate` (raw only), `language`, `format` (ITN, **requires `language`** or 400), `multichannel`, `channels` (2–8, raw only), `diarize`, `keyterm` (repeat, max 100), `filler_words`, `vad_threshold` (default **0.5**). No prompt / response_format / timestamp_granularities; word timestamps always come back.
- Containers auto-detected: wav, mp3, ogg, opus, flac, aac, mp4, m4a, mkv. **Max 500 MB**; no duration limit documented.
- Response: `text`, `language` (detected, BCP-47, e.g. `es-mx`), `duration` (s), `words[]` as above, `channels[]` `{index, language?, text, words}` when multichannel. No usage field.
```
{"text":"The balance is $167,983.15. That is $23.4 kilograms.","language":"en","duration":8.4,"words":[{"text":"The","start":0,"end":0.24,"confidence":0.33},...,{"text":"kilograms.","start":7.76,"end":8.4,"confidence":0.09}]}
```

## Languages
25 codes whose `language` enables formatting: ar, cs, da, de, en, es, fa, fil, fr, hi, id, it, ja, ko, mk, ms, nl, pl, pt, ro, ru, sv, th, tr, vi. "The model transcribes speech in any of these languages regardless of the `language` parameter"; 2.0 "detects the language automatically, and follows mid-recording switches". xAI's Rust client: "The STT API does **not** accept `auto`".

## Pricing / limits
- **$0.10/hr batch, $0.20/hr streaming** (both models; diarization, timestamps, keyterms included). `/developers/pricing`, model page ("$0.10 / hr (REST), $0.20 / hr (Streaming)"), and the model page's embedded catalog: `"perAudioSecond":"277778","perAudioSecondStreaming":"555556"` in 1e-10 USD ticks. Billed per audio second.
- Rate limits per team (voice tiers, by cumulative spend $0/$50/$250/$1k/$5k): STT RPS 10/10/20/30/40; concurrent sessions 100/200/200/300/500 (streaming).
- Region: `us-east-1`; `us.api.x.ai` does not serve voice. Voice overview claims audio is "never stored or used for training" and HIPAA-eligible with a BAA.

## Errors
- REST (guide): 400 bad request (no file/url, unsupported format, raw without `sample_rate`, `format` without `language`), 401, 413 (>500 MB), 429 (back off), 502 (`url` download failed), 503 (backend unavailable — retry).
- Probed 2026-09-23, same body on REST and on a refused WS upgrade: no credentials → **401** `{"code":"The request does not have valid authentication credentials","error":"No credentials presented. ..."}`; invalid key → **400** (not 401) `{"code":"Client specified an invalid argument","error":"Incorrect API key provided. ..."}`. `code` is a gRPC status description; the message is in `error`.

## Mapping
- Two slugs because the modes are priced differently and the catalog carries one price per slug: `xai/grok-voice-transcribe-2.0` (streaming, $0.20/hr) and `xai/grok-voice-transcribe-2.0-batch` (batch, $0.10/hr). The batch adapter strips `-batch`; the stream adapter refuses the batch slug (resolve_stream does not check modes, and streaming at the batch price would under-bill).
- Streaming: our `linear16`/`mulaw`/`alaw` → `pcm`/`mulaw`/`alaw`, mono only. Opus is not offered: one-packet-per-frame cannot survive a failover ring replay. `multichannel` is adapter-owned (it changes the event shape).
- **Finals**: chunk finals go out as interims; only `speech_final` becomes a final (+ `utterance_end` at its end) — the reading xAI's own client uses (`UtteranceFinal` on `speech_final`). Deepgram's "concatenate every `is_final`" would double the text if `speech_final` is the stitched utterance. Because that is undocumented (Open 1), the adapter decides per event from `start`: an event starting where the utterance started is cumulative and used as-is; one starting later is a tail and gets the locked chunk text/words prepended. Both readings produce the same client output.
- Word times are expected stream-absolute like `start`; words that precede their own event's `start` must be relative and are shifted (Open 3).
- `transcript.done`: a pending chunk final is flushed as a final, plus any of its words past the last final; its `text` is used only when nothing was final yet (Open 2).
- `language`: bare primary subtag (`en-US` → `en`), `auto` omitted. Batch sends `format=true` with it so both modes format the same.
- `filler_words` left at xAI's default (removed), same as Deepgram's default; opt in via `provider_params`.
- Errors: WS upgrade 400/401/403 non-recoverable, others recoverable. Close codes are undocumented, so every mid-session close is recoverable (failover decides). REST 429/5xx recoverable.
- No pacing bucket: nothing documents enforcement (Open 4).
- BYOK-able (single key): `xai_api_key`.

## Open (verify live)
1. **What `speech_final` carries** — the whole utterance or only the tail since the last chunk final — and whether `start`/`duration` on it span the utterance. The adapter handles both; confirm which, and whether interims after a chunk final are cumulative.
2. `transcript.done.text`: full session ("Full transcript" in the Python example) or only the flushed tail (schema example `""`)?
3. Are streaming word timestamps absolute from stream start?
4. Is faster-than-realtime input throttled or rejected? Matters for failover replay.
5. Close codes, keepalive, idle timeout, max session length.
6. Default model: release notes say 1.0, everything else says 2.0 — we always send `model`.
7. Batch `model` field is in the guide/examples but missing from the REST reference field list; confirm it is honoured.
8. Region subtags (`en-US`) accepted in `language`? Unlisted codes? Streaming events carry no detected language.
9. Streaming billing basis (audio seconds received vs connection time) and rounding.
10. WebM: listed on the model page, not in the format tables.
11. Are diarization speaker indices stable across a streaming session?
