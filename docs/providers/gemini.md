# Gemini Live Transcription — STT protocol brief (live-verified 2026-08-26)

Docs: `ai.google.dev/gemini-api/docs/live-api/live-transcribe`, `ai.google.dev/api/live`,
`ai.google.dev/gemini-api/docs/live-session`, `ai.google.dev/gemini-api/docs/pricing`.

**Not Google Cloud Speech-to-Text.** The `google/*` models in this repo are Cloud STT v2:
gRPC, a GCP project, a service-account JSON, a 5-minute stream cap. This is the **Gemini
API** — WebSocket, a single `GEMINI_API_KEY` from AI Studio, its own quota and its own
billing line. Same vendor, different product, so it gets its own provider id and its own
credential rather than a fourth model under `google/`.

## Realtime WS

- Endpoint:
  `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent`
- Auth: `?key=<API_KEY>` query param. (Ephemeral tokens exist for browser clients — a
  server-side gateway has no use for them.)
- Model: `gemini-3.5-transcribe-live`. There is also a non-live `gemini-3.5-transcribe`
  for batch, which **does** have diarization and word timestamps — out of scope here, it
  is a different (non-Live) surface. See Open (7).
- Handshake: first client frame is `setup`, server replies `setupComplete`. **Audio sent
  before `setupComplete` is dropped**, so `connect()` blocks on it — the
  `STTStreamProvider` contract already requires that.
- Audio up: JSON text frames, base64 inside
  `realtimeInput.audio {data, mimeType: "audio/pcm;rate=16000"}`. Raw 16-bit
  little-endian **mono PCM at 16 kHz**; docs recommend ~100 ms chunks.
- End of audio: `realtimeInput.audioStreamEnd: true`. **This is mandatory, not
  optional** *(live)*: stop sending audio and simply wait, and no final ever arrives —
  the endpointer does not fire on silence. A controlled A/B confirmed it (half the clip
  then `audioStreamEnd` → final in ~0.7 s; half the clip then 6 s of waiting → nothing).
  That makes the flush in `finish()` and the pre-swap flush in rotation load-bearing.
  The value must be the boolean `true`; the object form `{}` is rejected with a **1007**
  close, `Invalid value at 'realtime_input' (audio_stream_end)`.
- Manual VAD: `realtimeInputConfig.automaticActivityDetection.disabled` plus
  `activityStart` / `activityEnd` frames. Exposed through `provider_params`, not wired to
  a unified knob — nothing above the adapter has a push-to-talk concept.

```json
{"setup": {
  "model": "models/gemini-3.5-transcribe-live",
  "generationConfig": {"responseModalities": ["TEXT"]},
  "inputAudioTranscription": {"languageCodes": [], "customVocabulary": [], "mode": "VERBATIM"},
  "sessionResumption": {}
}}
```

## Response

JSON text frames. Two transcript fields, both under `serverContent`:

- `interimInputTranscription.text` — speculative partials while the speaker is talking.
- `inputTranscription.text` — finalized text, emitted at turn completion.

**The end-of-turn signal is `serverContent.generationComplete`, not `turnComplete`.**
*(live)* The docs describe `turnComplete`; this model never sends it. A 12.5 s utterance
produced 26 interim frames, then exactly one `inputTranscription`, then
`generationComplete`. The adapter accepts either key so a future `turnComplete` still
ends a stream cleanly — watching only for the documented one made `finish()` wait out its
full grace timeout on every single stream.

**`inputTranscription` is the whole utterance, not a fragment** *(live)*: one 196-char
final for the whole 12.5 s clip. Concatenating finals is still the right client
behaviour, but nothing needs reassembly.

Other frames seen on the wire: `setupComplete`, and bare `{"serverContent": {}}` with no
keys at all — harmless, and the parser must not trip on them. `usageMetadata` is
documented but **never arrives on this model** *(live)*; `sessionResumptionUpdate` never
arrives either (see below).

**No timestamps anywhere.** Docs are explicit: no word-level timestamps in live mode
(utterance-level only), no diarization, no confidence, no speaker labels — and no
timestamp field appears on the transcription payload at all. So every `Transcript` this
adapter emits has `start=None`, `end=None`, `words=None`, exactly like `telnyx`.

That has one consequence worth stating plainly: `router/session.py` `_normalize()`
suppresses replayed finals by comparing a final's `end` against `_last_final_end`, and a
final with no `end` never reaches that gate. **Failover into or out of this provider can
therefore repeat text covering ring-buffer audio.** Synthesising an `end` from the ingest
cursor would make the gate look like it works while deduping on a number the provider
never reported, so the adapter does not do it. Fixing this properly means a
sequence-based dedup path in the session layer, not a fake timestamp in the adapter.

## Connection lifetime and rotation

- Audio-only Live sessions run to 15 minutes, but **the connection itself lives about 10
  minutes**; the server sends `goAway {timeLeft}` and then closes as ABORTED. The
  live-transcribe page states the shorter figure directly: "sessions support continuous
  streaming for up to 10 minutes".
- `sessionResumption` is accepted in `setup`, but **this model issues no handles**
  *(live)* — zero `sessionResumptionUpdate` frames across a full stream. So rotation
  reconnects as a fresh session. That costs nothing for transcription (there is no
  conversational context to carry), and the request stays in the setup message for
  whenever it starts working.
- The adapter therefore **rotates its own socket** at 9:00, or immediately on `goAway`.
  Same shape as `google/adapter.py`, which rotates under Cloud STT's 5-minute cap. Before
  the swap it sends `audioStreamEnd` on the outgoing socket and reads for up to 1.5 s so
  the in-flight utterance arrives as a final instead of being lost. Audio arriving during
  the swap is buffered (capped at 30 s) rather than blocking `send_audio`: a stall there
  would surface as a latency spike in a live agent every nine minutes.
- **Verified end to end** *(live)*: with `ROTATE_SECONDS` shrunk to 12 s, ~40 s of audio
  crossed three rotation boundaries and produced three finals with no gap — the tail of
  each pass reappears at the head of the next final, which is the buffered audio arriving
  on the new socket exactly as designed.
- `contextWindowCompression` is the vendor's own answer to the length limit, but it
  extends the *session*, not the *connection* — it does not remove the need to rotate.
  Reachable through `provider_params` for callers who want it.

## Options

- `languageCodes: []` is the API's spelling of automatic detection; a list constrains
  recognition. ~85 BCP-47 codes, in `models.json`.
- `customVocabulary`: up to 1000 phrases, "best results with ≤100". Mapped from the
  unified `keyterms` → `Capabilities.keyterms_max = 1000`.
- `mode`: `VERBATIM` (default — keeps fillers, repetitions, false starts) or `SMART`
  (disfluency removal, punctuation, grammar, casing). Docs note SMART cannot combine with
  word annotations, which costs us nothing since there are no word timings either way.

## Errors

- Bad key shows up either as a failed upgrade (401/403) or as a close after `setup`;
  both paths are handled, and the key is stripped from error text before it can reach a
  log (`websockets`' `InvalidURI` quotes the URL back).
- Application errors arrive as `{"error": {"code", "message", "status"}}`.
  `INVALID_ARGUMENT` / `PERMISSION_DENIED` / `NOT_FOUND` / `UNAUTHENTICATED` are
  unrecoverable — the same setup reproduces them exactly. Everything else, plus close
  codes other than 1008, is recoverable and triggers failover.

## Pricing — CHECK THIS BEFORE IT BILLS ANYONE

`models.json` carries **`per_audio_hour_usd: 0.30`**, the announced headline rate.

**It does not match the published pricing page**, and that page is the only Google
source found for this model's rates (`ai.google.dev/gemini-api/docs/pricing`, read
2026-08-26; the launch post, `blog.google/.../gemini-3-5-transcribe/`, quotes no price
at all). The page bills tokens, not minutes:

| Line | Rate |
| --- | --- |
| Input (audio) | `$3.50/1M` or **`$0.005/min`** |
| Output (text) | `$21.00/1M` or **`$0.004/min`** |
| Google's own blended footnote | **`~$0.009/min`** = **$0.54/hr**, at 25 audio tok/sec in and 175 text tok/min out |

$0.30/hr is exactly $0.005/min — **the audio-input line on its own**, with the text
output unpriced. So either the announced headline supersedes the page (and the page is
stale), or $0.30/hr undercounts by whatever the text output costs, which on Google's own
25/175 token assumption is ~$0.24/hr more.

We meter and bill from this number. Close it with the `usage` experiment in
`scripts/gemini_probe.py`: it reads `usageMetadata` off a real stream and prints actual
$/min next to the catalog rate. Until then, treat $0.30/hr as **unverified**.

For reference the non-live `gemini-3.5-transcribe` blends to ~$0.005/min on the same page.

## Verified against a live key (2026-08-26)

Run: `scripts/gemini_probe.py --exp all`, plus a shortened-timer integration run of the
real adapter. Everything below is measured, not read.

| Question | Answer |
| --- | --- |
| Whole utterances or fragments? | **Whole.** One 196-char final for a 12.5 s clip, after 26 interims. |
| Does `sessionResumption` issue handles? | **No.** Zero handles; rotation reconnects fresh. |
| Does `audioStreamEnd` flush the tail? | **Yes, and it is the only way** — without it nothing arrives at all. |
| Is the connection reusable after it? | Not needed either way: rotation and `finish()` both discard that socket. |
| End-of-turn signal | **`generationComplete`** — `turnComplete` is documented but never sent. |
| Is a non-16k rate accepted? | The mimeType rate is **honoured, not ignored**: 16 k audio declared as 8 k transcribed as garbage rather than erroring. Real 8 k audio would likely work, but only 16000 is claimed in `models.json`. |
| Does `SMART` mode work? | **Yes.** `"Um, let's meet Tuesday—no, Wednesday—…, uh, cover everything"` → `"Let's meet Wednesday to review…cover everything"`. |
| Can token spend be metered? | **No.** `usageMetadata` never arrives — see Pricing. |

## Open

1. **Which price is right — $0.30/hr or $0.54/hr?** See Pricing. The wire cannot answer
   it: `usageMetadata` is never sent, so the `usage` probe experiment comes back empty.
   Next best source is the billing console after a day of real traffic.
2. Does the ~10-minute cap really land at 10 minutes? Rotation is verified, but at a
   shortened timer; the real `goAway` has not been observed. `ROTATE_SECONDS = 540` has
   90 s of headroom against the documented figure either way.
3. Should `generationComplete` map to `utterance_end`? It is a real VAD edge, but
   `UtteranceEnd.at` is a timestamp and this wire has none — so it is deliberately not
   emitted rather than emitted with a fabricated time.
4. `gemini-3.5-transcribe` (non-live) as a batch model: the launch post promises speaker
   attribution and word-level timestamps, ~$0.005/min. It ships on the **Interactions
   API**, not the Live socket and not `generateContent`, so it needs its own `batch.py`.

## TTS (added 2026-10-13, SR-TTS-LIVE) — documented, NOT yet live-verified

- `POST v1beta/models/{m}:streamGenerateContent?alt=sse`, key in `x-goog-api-key` (never `?key=`).
- Body: `contents[{role:user, parts:[{text}]}]`, `generationConfig {responseModalities:["AUDIO"],
  speechConfig {voiceConfig {prebuiltVoiceConfig {voiceName}}, languageCode?}}`; multi-speaker via
  `provider_params.speechConfig.multiSpeakerVoiceConfig`.
- Output: `candidates[0].content.parts[].inlineData {mimeType:"audio/L16;codec=pcm;rate=24000", data}` —
  raw PCM only. The gateway wraps wav / G.711 (8 kHz).
- Style: no `instructions` field; the gateway prefixes the prompt (`"<instructions>: <text>"`), billed as
  text tokens.
- Usage: `usageMetadata {promptTokenCount (text in), candidatesTokenCount (audio out)}`, treated as
  cumulative (last wins). Fallback: 25 audio tokens/s, 4 chars/text token. **Probe:** `--exp gemini_tts`.
- Pricing: gemini-3.8-flash-tts $0.50 / $9.00 per 1M (text in / audio out), flash-lite $0.50 / $6.00,
  **doubling on 2027-01-01** (catalog `pricing_schedule`).

## Live passthrough (added 2026-10-13) — documented, NOT yet live-verified

- Same socket as transcription above; the gateway forwards frames verbatim. The model comes from
  `setup.model` in the FIRST frame, so the gateway reads one frame before dialing.
- google-genai (2.30) builds `wss://<base>/ws/google.ai.generativelanguage.<ver>.GenerativeService.
  BidiGenerateContent` and puts the key in its http_options headers (`x-goog-api-key`). Ephemeral
  `auth_tokens/…` switch to `BidiGenerateContentConstrained` with `Authorization: Token`. **It always
  forces `wss://`**, so a self-hosted gateway needs TLS for Gemini Live. The SDK sends snake_case
  top-level keys (`realtime_input`); the meter accepts both spellings.
- Server frames are JSON in **binary** WS frames; passthrough keeps the frame type.
- **Open: `usageMetadata` semantics on Live** — per message (sum) vs cumulative (max). Default
  `per_message` (`SPEECHROUTER_GEMINI_LIVE_USAGE_SEMANTICS`). Settle with `--exp gemini_live` plus the
  billing console. Modality split from `promptTokensDetails` / `responseTokensDetails`
  (`cacheTokensDetails` subtracted out); without details, prompt → audio in, response → audio out,
  flagged `units_estimated`.
- Fallback estimate: 1667 tok/min in, 1500 tok/min out (from the per-minute prices on Google's page).
- Pricing (per 1M): gemini-3.8-live text 0.75 / audio 3.00 / image·video 1.00 in, text 4.50 / audio 12.00 out.
