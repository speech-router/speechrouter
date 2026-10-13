# PLAN — TTS + Live (realtime voice) for the SpeechRouter gateway

Task SR-TTS-LIVE · written 2026-10-13 · status: **plan only, no code yet**

Scope: add text-to-speech (TTS) and bidirectional realtime voice ("live") for
**OpenAI** (TTS + GPT Realtime) and **Google Gemini** (Gemini TTS + Gemini Live) to
`gateway/`. The cloud app (`speech-router/cloud`, Rails) follows in a separate session;
§3 lists exactly what it needs.

---

## 0. What exists today (findings that shape the design)

| Area | Today | Implication |
|---|---|---|
| Provider plugin | `providers/base.py`: `STTStreamProvider` / `STTBatchProvider` + `Capabilities`; `providers/registry.py` self-registration keyed by provider id; builders raise `ProviderNotConfigured` | Add `TTSProvider` + `register_tts` in the same style. Live does **not** fit the adapter contract (see §2). |
| Routing | `router/resolver.py`: slug `provider/model` → validated `ResolvedAttempt` before any upstream dial; catalog lookup by slug | Add `resolve_tts` and `resolve_live`. Catalog entries need `kind` checks: an STT slug must not resolve as TTS. |
| Catalog | `providers/*/models.json` merged by `router/catalog.py`; `catalog.schema.json` **already has** `kind: stt\|tts`, `capabilities.voices`, `pricing.per_character_usd` | TTS is anticipated. Live needs a new `kind` value and token pricing fields. |
| Spec | `packages/spec/events.schema.json` **already defines** `/v1/speak`: `text.delta`, `clear`/`cleared{last_seq}`, `audio.chunk{seq,start,word_timestamps}`, `finalize`, `done{usage.characters,cost_usd}`. Spec README decision 5 settles TTS framing (JSON text in, binary audio out). Pydantic models in `protocol/events.py` are generated (`scripts/codegen.sh`) and CI fails on drift. | TTS WebSocket needs no protocol design, only an implementation. Every spec change goes through codegen. |
| Auth | `auth/tokens.py: resolve_credentials` (keys + `st_` short-lived tokens), `org_blocked`, `apply_byok` (single-field providers incl. `openai`, `gemini`), per-scope `ConcurrencyGuard` | Reuse as-is. BYOK already works for both providers. |
| Metering | `metering/emitter.py: UsageEvent{kind: stt_stream\|stt_batch\|tts_stream\|tts_batch, characters, audio_seconds, billed_seconds, billing_basis, ...}` → Redis stream `speechrouter:usage`; mid-session credit cut via `speechrouter:balance:<org>` every 30 s (`router/session.py::_check_credits`) | TTS kinds and `characters` already exist. **Token-priced** models (gpt-4o-mini-tts, all Gemini TTS, all realtime/live) have no field to carry token counts. |
| Gemini | `providers/gemini/adapter.py` already speaks raw BidiGenerateContent (setup → setupComplete, goAway/rotation, live-verified quirks) | Reuse that wire knowledge for Gemini Live, not the class (that one is STT-only). |
| OpenAI | `providers/openai/adapter.py` speaks Realtime GA (`?intent=transcription`, nested `session.audio.input`) | Same: reuse the wire knowledge. |
| Baseline | `uv run --directory gateway pytest -q` → **292 passed** on `main` (226bffe); CI also runs ruff, pyright, spec-drift | |

### Cloud findings (read-only survey of `speech-router/cloud`)
These are **billing blockers**. Without cloud changes, TTS and live usage would be
recorded and never charged:
- `lib/tasks/speechrouter.rake` (`sync_models`) only understands `per_audio_{second,minute,hour}_usd`
  and `per_session_hour_usd`. Any model priced per character or per token is **skipped**. Its
  events land with `price_microusd = nil`, are never charged, and only produce a `warn` log.
- `model_prices` holds **one rate per slug**, so it can't express "text-in $X + audio-out $Y".
- `UsageConsumerJob` deduplicates on `session_id` (`create_or_find_by!`). A second event for the
  same session is silently dropped.
- An exception in `process` (e.g. `characters` overflowing int4) leaves the entry un-acked, and
  it is reclaimed first on every run. **One poison event halts all billing.**
- `billing_basis` is ignored, and `kind` and `characters` are stored but never used for pricing.
  Dashboard, Logs, Playground and Models pages are all STT-specific.

**Consequence:** the gateway must ship TTS and live behind feature flags that stay **off in cloud
mode until cloud billing is deployed** (§1.6, §2.8).

---

## 1. TTS

### 1.1 API surface

**A. `POST /v1/audio/speech` (OpenAI-compatible, the default path)**

```jsonc
// request (application/json)
{
  "model": "openai/gpt-4o-mini-tts",      // our slug; required
  "input": "Hello there",                  // required, ≤ per-model max (OpenAI 4096 chars)
  "voice": "coral",                        // provider-native voice id; default per catalog entry
  "response_format": "mp3",                // mp3|opus|aac|flac|wav|pcm|mulaw|alaw (per-model subset)
  "sample_rate": 24000,                    // optional, only for pcm/mulaw/alaw; validated against caps
  "speed": 1.0,                            // optional, 0.25–4.0 where supported
  "instructions": "warm, unhurried",       // optional style prompt (gpt-4o-mini-tts, Gemini)
  "language": "en-US",                     // optional (Gemini)
  "stream": true,                          // default true: chunked response as audio arrives
  "provider_params": { }                   // passthrough escape hatch, as in STT
}
```
- **Response:** `200` with `Content-Type` matching the format (`audio/mpeg`, `audio/ogg`,
  `audio/wav`, `audio/L16;rate=24000`, …) and the body streamed with chunked transfer as the
  provider produces it, so time-to-first-byte is the provider's. Metadata goes in headers:
  `X-SpeechRouter-Request-Id`, `X-SpeechRouter-Model`, `X-SpeechRouter-Characters`. Errors after
  the first byte cannot change the status, so the stream is cut and the failure is logged and
  metered as `provider_error`. That is the same tradeoff OpenAI makes.
- Errors use the existing OpenAI envelope and status map from `api/transcriptions.py::_error`.
- Drop-in for the OpenAI SDK: `client.audio.speech.with_streaming_response.create(model="openai/gpt-4o-mini-tts", ...)`
  with `base_url=https://api.speechrouter.ai/v1`.

**B. `WSS /v1/speak` (incremental text in, for voice agents; protocol already specified)**
- Query: `model, voice, encoding (linear16|mulaw|alaw|opus|mp3), sample_rate, speed, language, instructions, provider_params`.
  Auth is the same as `/v1/listen` (Bearer header, `bearer,<key>` subprotocol, `?api_key=`).
- Client → server: `text.delta{text}`, `finalize`, `clear`, `keepalive`.
  Server → client: `session.open`, then per chunk an `audio.chunk{seq,start}` text frame followed by
  one binary frame, then `cleared{last_seq}`, `done{usage}` and `error`.
- **OpenAI and Gemini have no incremental-text TTS socket.** Both are request/response, so
  `/v1/speak` is implemented **gateway-side** for them:
  - A `TextSegmenter` buffers deltas and cuts on sentence boundaries (`. ! ? 。` + newline, with a
    min-length / max-wait guard of about 40 chars or 400 ms) and on `finalize`.
  - Each segment becomes one streaming `synthesize()` call. Segments are pipelined one ahead
    (prefetch N+1 while N plays), and output order is preserved.
  - `clear` cancels in-flight HTTP requests, drops queued segments, and answers
    `cleared{last_seq}`. Audio already generated is still metered, because the provider charged
    for it.
- Native WebSocket TTS providers (ElevenLabs, Cartesia, Deepgram Aura) get native adapters
  later (Phase 2), behind the same `/v1/speak` protocol.

`/v1/speak` is a v1 nicety. **Recommendation: ship `POST /v1/audio/speech` first (PR 2) and
`/v1/speak` in PR 3.**

### 1.2 Provider abstraction

```python
# providers/base.py (additions)
@dataclass(frozen=True)
class TTSCapabilities:
    streaming: bool = True               # chunked output
    voices: frozenset[str] = ...         # provider-native ids; also published in catalog
    default_voice: str = ""
    formats: frozenset[str] = ...        # our canonical names
    sample_rates: frozenset[int] = ...
    max_input_chars: int = 0
    instructions: bool = False           # style prompt support
    speed: bool = False
    word_timestamps: bool = False        # none for OpenAI/Gemini

@dataclass(frozen=True)
class TTSConfig:
    model: str; voice: str; format: str; sample_rate: int
    speed: float | None = None; instructions: str | None = None
    language: str | None = None; provider_params: dict = field(default_factory=dict)

@dataclass
class TTSUsage:                         # filled in by the adapter as the stream completes
    characters: int = 0
    audio_seconds: float = 0.0
    tokens: dict[str, int] = field(default_factory=dict)  # e.g. {"text_in": 12, "audio_out": 410}

class TTSProvider(ABC):
    name: str
    capabilities: TTSCapabilities
    @abstractmethod
    def synthesize(self, text: str, config: TTSConfig, usage: TTSUsage) -> AsyncIterator[bytes]:
        """Yield encoded audio chunks in config.format. Raise ProviderStreamError.
        Must fill `usage` by exhaustion (or best effort on cancel)."""
    async def close(self) -> None: ...
```
- `registry.py`: `register_tts(provider_id, capabilities=...)` and `tts_provider(id)`.
- `resolver.py`: `resolve_tts(slug, request, settings, catalog) -> ResolvedTTS`. It requires
  `entry.kind == "tts"`, then validates voice, format, rate, input length, and credentials (the
  same probe-build pattern as STT). `resolve_batch`/`resolve_stream` gain an `entry.kind == "stt"`
  check, so a TTS slug can't be used for transcription.
- **No fallbacks for TTS in v1.** A failover would switch voices mid-utterance, so it is a
  product decision rather than a free win. Pre-first-byte retry on a different model could
  come later (open question).
- **Audio format handling:** never transcode with ffmpeg in the hot path. Each model declares
  only the formats it produces natively, plus cheap gateway-side wrappers:
  - `pcm` → `wav`: a 44-byte header (streamed with the "unknown length" convention, size
    `0xFFFFFFFF`).
  - `pcm` → `mulaw`/`alaw`: a pure-Python G.711 table encoder. `audioop` was removed in Python
    3.13, so it is a small vendored table of about 40 lines. This lets telephony users get
    8 kHz G.711 from Gemini too, with resampling 24k→8k by a simple polyphase/decimation filter.
    **Defer resampling to a follow-up** unless it is cheap to validate.

### 1.3 Providers, first wave

| Slug | Upstream | Formats | Voices | Usage source | List price (verified 2026-10-13) |
|---|---|---|---|---|---|
| `openai/gpt-4o-mini-tts` | `POST /v1/audio/speech`, `stream_format=sse` | mp3, opus, aac, flac, wav, pcm(24k) | alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer, verse, marin, cedar (verify list at impl) | SSE `speech.audio.done.usage {input_tokens, output_tokens}` | $0.60/1M text in · $12.00/1M audio out |
| `openai/tts-1` | same, raw audio stream | same | same minus newest | characters (gateway counts) | $15.00/1M chars |
| `openai/tts-1-hd` | same | same | same | characters | $30.00/1M chars |
| `gemini/gemini-3.8-flash-tts` | `POST v1beta/models/{m}:streamGenerateContent?alt=sse`, `responseModalities:["AUDIO"]`, `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName` (header `x-goog-api-key`, **not** `?key=`, to keep keys out of URLs/logs) | pcm 24k s16le mono (native); wav, mulaw/alaw via wrappers | ~30 prebuilt (Kore, Puck, Charon, Zephyr, …; pull list at impl) | `usageMetadata {promptTokenCount, candidatesTokenCount}`; fallback 25 audio tokens/s | $0.50/1M text in · $9.00/1M audio out **until 2026-12-31, then $1.00 / $18.00** |
| `gemini/gemini-3.8-flash-lite-tts` | same | same | same | same | $0.50 · $6.00 (→ $1.00 · $12.00 on 2027-01-01) |
| `gemini/gemini-2.5-pro-preview-tts` (optional) | same | same | same | same | $1.00 · $20.00 |

- Gemini multi-speaker TTS (`multiSpeakerVoiceConfig`) is reachable through `provider_params`
  in v1, with no first-class API.
- **The Gemini price doubles on 2027-01-01.** The catalog needs either a dated price or a
  reminder to bump it. See open question Q6.
- For OpenAI, **always request SSE internally**, even when the client wants raw bytes. SSE is
  the only path that returns token usage. The gateway decodes the base64 `speech.audio.delta`
  events and streams the raw bytes out.

**Phase 2 (existing providers with TTS, single-key so BYOK already works):** ElevenLabs
(`eleven_flash_v2_5`, `eleven_v3`, native WS input streaming), Cartesia (`sonic-2`/`sonic-3`,
native WS with contexts), Deepgram (`aura-2`, native WS `Speak`/`Flush`/`Clear`). These are the
ones the cloud's "Coming soon · TTS" list already advertises, along with `azure/neural-tts`,
which is multi-field credentials and so not BYOK-able. Also worth a look: AWS Polly, Google
Cloud TTS, Azure, xAI and Mistral voice. **Out of scope for this ticket.**

### 1.4 TTS metering
- One `UsageEvent` per request (`kind="tts_batch"`) or per `/v1/speak` session
  (`kind="tts_stream"`), emitted exactly once from `finally`, like STT.
- `characters` = `len(input)` in Unicode code points, counting what was *sent upstream* (after
  `clear`, only the segments actually dispatched).
- `audio_seconds` = generated audio duration. It is exact for PCM, computed from byte count; for
  compressed formats it is estimated from tokens (Gemini 25 tok/s) or from the SSE `speech.audio.done`.
- New field `units: dict[str, float]` (see §1.5) carries the priced quantities, e.g.
  `{"text_input_tokens": 12, "audio_output_tokens": 410}` or `{"characters": 1200}`.
- `Done.usage.cost_usd` (already in the spec) is filled from the catalog list price for
  `/v1/speak`; REST returns it as `X-SpeechRouter-Cost-Usd`. Both are informational, and cloud
  stays the biller.
- Credit enforcement: admission uses `org_blocked` as today. A `/v1/speak` session runs the same
  30 s balance check, using cost accrued from units.

### 1.5 Pricing / metering model change (shared by TTS and live)
The current model of "one rate × billed_seconds" cannot price token models. Proposal:

1. **Catalog** (`catalog.schema.json` `pricing`): allow **multiple** rate fields per model.
   Add `per_1m_text_input_tokens_usd`, `per_1m_cached_text_input_tokens_usd`,
   `per_1m_audio_input_tokens_usd`, `per_1m_cached_audio_input_tokens_usd`,
   `per_1m_image_input_tokens_usd`, `per_1m_text_output_tokens_usd` and
   `per_1m_audio_output_tokens_usd`, plus the existing `per_character_usd`. Also add
   `effective_from`/`effective_until` (or a `price_schedule` array) for the Gemini step-up.
   This breaks the schema rule "Exactly one rate field per model", so `_derive_legacy_pricing`
   must **not** emit `per_second_usd` for token-priced models. Legacy consumers must see them
   as unpriced rather than mispriced.
2. **UsageEvent**: add `units: dict[str, float]` of raw counts keyed by unit name
   (`characters`, `text_input_tokens`, `cached_text_input_tokens`, `audio_input_tokens`,
   `cached_audio_input_tokens`, `image_input_tokens`, `text_output_tokens`, `audio_output_tokens`).
   Each key maps 1:1 to a catalog rate field (`audio_output_tokens` ↔ `per_1m_audio_output_tokens_usd`).
   Price = Σ `units[k] × rate[k]` (÷1e6 for token rates). Keep `audio_seconds`, `billed_seconds`
   and `characters` for dashboards and backward compatibility.
3. **Gateway also emits `list_cost_usd`** (computed from its own catalog) as a cross-check.
   Cloud prices from its synced table, and a mismatch is alertable.
4. `kind` gains `live`. A new `parent_session_id` supports checkpoint events (§2.6).

### 1.6 Config / flags
`config.py`: `enable_tts: bool = True`, `enable_live: bool = True` for self-host. Cloud deploys set
them `false` until cloud billing ships. The catalog endpoint hides disabled kinds so the
dashboard doesn't advertise them. Also add `max_tts_input_chars` and `max_concurrent_live`
(separate cap, default 5/org: live sessions are ~10–50× pricier per minute than STT).

---

## 2. Live mode (OpenAI Realtime, Gemini Live)

### 2.1 Decision: **provider-native WebSocket passthrough first**, normalized protocol later

| | Passthrough (recommended v1) | Normalized SpeechRouter protocol |
|---|---|---|
| Client code | Unchanged official SDKs (OpenAI SDK / Agents SDK realtime, `google-genai` live) via base-URL override, the same strategy as the existing Deepgram-compat dialect | New SDK surface; nobody's existing code works |
| Feature coverage | 100%: tools, function calls, conversation items, images, transcription, VAD config, session resumption, new events on day 1 | Lowest common denominator; every upstream release needs mapping work |
| Effort | ~1 proxy core + 2 thin dialect shims | Large; two complex state machines to normalize |
| Cross-provider routing | No (model is picked by the client's SDK) | Yes |
| Failover | Impossible either way (conversation state lives upstream) | |

The gateway's job in passthrough mode: **auth, key swap (house/BYOK), model allow-listing,
limits, metering, observability, error shaping**. It forwards frames verbatim and only
*inspects* them, so it should be cheap.

A normalized "voice agent" protocol (`/v1/agent` with `input_audio` binary frames, normalized
`transcript`, `response.audio`, `tool_call` events) is a possible **Phase 3**. See Q1.

### 2.2 Endpoints and auth

| Dialect | Gateway path (mirrors upstream so SDK base-URL overrides just work) | Upstream | Client auth accepted |
|---|---|---|---|
| OpenAI | `WSS /v1/realtime?model=openai/gpt-realtime-2.1` (bare `gpt-realtime-2.1` also accepted → prefixed `openai/`) | `wss://api.openai.com/v1/realtime?model=<m>` + `Authorization: Bearer <house/BYOK key>` | `Authorization: Bearer <sk/st>`; browser subprotocol `openai-insecure-api-key.<st_token>` (what OpenAI's browser path uses), plus our `bearer,<key>` |
| Gemini | `WSS /ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent` (+ `v1alpha`) and an alias `WSS /v1/live/gemini` | `wss://generativelanguage.googleapis.com/ws/…BidiGenerateContent` + header `x-goog-api-key` | `x-goog-api-key: <sk>`, `?key=<sk/st>` (SDK default), `?access_token=<st>` (ephemeral-token style), `Authorization: Bearer` |

- **Model for Gemini** arrives in the first client frame `setup.model = "models/gemini-3.8-live"`.
  The gateway must parse frame #1 before dialing upstream, map it to slug `gemini/gemini-3.8-live`,
  validate it against the catalog (`kind == "live"`), then forward the setup unchanged.
- **Ephemeral tokens.** Our existing `POST /v1/tokens` (`st_…`, 10–300 s TTL, connect-only) is
  the browser story for both. Add an OpenAI-shaped alias `POST /v1/realtime/client_secrets`
  returning `{value: "st_…", expires_at}`, so OpenAI browser samples work unchanged. The
  `session` config it receives can optionally be pinned into the token (open question Q3).
  Google's ephemeral-token flow (`authTokens.create`, v1alpha) is the analogue; we accept
  `st_` tokens where the SDK puts its token.
- **Never forward client credentials upstream, and never echo the upstream key.** Strip
  `Authorization`, `x-goog-api-key`, the `key` query param and the subprotocol before dialing.
- WebRTC and SIP (OpenAI) are **out of scope**: proxying media over WebRTC needs an SFU. Document
  WebSocket only.

### 2.3 Proxy core (`live/proxy.py`)
```
client WS ──(pump A: client→upstream)──▶ upstream WS
client WS ◀──(pump B: upstream→client)── upstream WS
          watchdog (limits, credit check)   meter (inspects frames, both directions)
```
- One `LiveSession` per client socket. `asyncio.TaskGroup` of pump A, pump B and the watchdog.
  The first one to finish closes the other side with the same close code and reason
  (sanitized), then usage is emitted once from `finally`.
- Frames are forwarded **as received** (text stays text, binary stays binary). JSON is parsed only
  for inspection: the `type` (OpenAI) or top-level key (Gemini), plus usage fields. The parse
  happens off the forward path's critical section, so forwarding never waits on metering.
- `websockets` dial with `max_size` ≈ 16 MB (OpenAI allows large `conversation.item.create` with
  images) and `compression=None` (audio frames are base64 and compress poorly). Pings come from
  the websockets library.
- **Policing (minimal):**
  - OpenAI: reject `session.update` attempts to change `model`, since the model is fixed by
    URL and fixed per session upstream anyway.
  - Gemini: reject a second `setup`.
  - Optional per-org allow-list of tools/modalities later.
- **Backpressure:** no queues between the pumps. `await upstream.send()` blocks pump A, which
  naturally slows reading the client socket.

### 2.4 Session lifecycle
1. Accept the WS (echo the offered subprotocol as `/v1/listen` does). Auth goes through
   `resolve_credentials`, then `org_blocked`, then the feature flag.
2. Resolve the model. OpenAI: from the query. Gemini: read the first frame with a 10 s timeout.
   `resolve_live` checks the catalog entry `kind == "live"`, the dialect matches the provider,
   and credentials exist. `apply_byok` swaps the key.
3. `ConcurrencyGuard` acquires on a **separate live scope** (`live:<org>`, `max_concurrent_live`).
4. Dial upstream (15 s timeout via `wsconnect.ws_connect`), then start the pumps.
   - OpenAI: the upstream `session.created` flows to the client naturally.
   - Gemini: forward the buffered setup, and `setupComplete` flows back.
5. Watchdog every 1 s:
   - `max_live_session_seconds`, default 60 min. OpenAI caps sessions at 60 min upstream.
     Gemini connections live ~10 min with `goAway`, and sessions resume via handle on a **new**
     client connection, which works transparently in passthrough since each reconnect is a new
     gateway session.
   - Idle timeout: any frame either way is activity. Default 120 s, because the provider's own
     idle limits apply too.
   - Every 30 s, a credit check against accrued cost.
6. Teardown: cancel the pumps, close both sockets, release the slot, emit final usage.
   Linger ≤3 s for the client close, as in `listen_ws.py`.

### 2.5 Errors
- **Before upstream is open** (auth, credits, unknown model, concurrency, flag off): send one
  error **in the dialect's native shape**, then close.
  - OpenAI: `{"type":"error","event_id":…,"error":{"type":"invalid_request_error","code":"<our Code>","message":…}}`
    then close 1008.
  - Gemini: close with code 1008 (policy) and reason `"<code>: <message>"` truncated to 123 bytes.
    That is how Google itself rejects, so SDKs surface it.
  - Codes are reused from the existing closed enum (`auth_failed`, `insufficient_credits`,
    `concurrency_exceeded`, `model_not_found`, `provider_error`, `session_expired`, …). No new
    codes are needed.
- **Upstream handshake failure:**
  - 401/403 with a house key: `provider_error`, a customer-facing message, and an internal
    alert via `alerting.report_provider_failure`.
  - BYOK: pass through the raw message, as STT does.
- **Upstream closes mid-session:** propagate the close code and reason to the client. Provider
  `error` events pass through untouched; they are the provider's protocol.
- **Gateway-initiated cut** (credits, max duration):
  - OpenAI: inject an `error` event, then close.
  - Gemini: close 1008 with a reason. Don't fabricate provider frames such as `goAway`.
- **The gateway crashes:** the client sees 1011. Usage up to the last checkpoint is already
  emitted (§2.6).

### 2.6 Usage tracking for live
Inspect server→client frames:
- **OpenAI** `response.done.response.usage`:
  - `input_token_details {text_tokens, audio_tokens, image_tokens, cached_tokens, cached_tokens_details{text_tokens,audio_tokens,image_tokens}}`
  - `output_token_details {text_tokens, audio_tokens}`
  - Usage is **per response**, so sum across responses. Also meter `conversation.item.input_audio_transcription.completed`
    usage if input transcription is enabled. It is billed at the transcription model's rate:
    a second line item, which needs a sub-unit key like `transcription_audio_input_tokens@openai/gpt-4o-mini-transcribe`.
    See Q4.
- **Gemini** `usageMetadata {promptTokenCount, responseTokenCount, promptTokensDetails[{modality, tokenCount}], responseTokensDetails[...], cachedContentTokenCount}`.
  **Unverified: is it cumulative per session or per turn?** The transcribe-live model never sent
  it at all (docs/providers/gemini.md). This has to be live-probed (extend `scripts/gemini_probe.py`).
  The implementation handles both: track the max of the cumulative values, or the sum if per-turn.
- **Fallback when usage never arrives.** Estimate from audio actually relayed:
  - Decode the base64 length of `input_audio_buffer.append` / `realtimeInput.audio` and of
    `response.output_audio.delta` / `serverContent.modelTurn.parts[].inlineData`, giving seconds
    in and out.
  - Convert seconds to tokens at the provider's documented rate (Gemini 25 tok/s; OpenAI TBD,
    probe it).
  - Mark the event `units_estimated: true`.
- **Session seconds** (wall clock) are always reported, for dashboards ("live minutes") and
  abuse detection.
- **Checkpointing:** a live session can run 60 min at up to ~$5/hr. Losing it on a gateway
  restart is real money, so emit a **delta usage event every 60 s** with
  `session_id = "<sess>:<n>"` and `parent_session_id = "<sess>"`, and a final one at close.
  Each id is unique, so cloud's existing `session_id` idempotency still holds. Cloud aggregates
  by parent for display. See Q5.

### 2.7 Catalog entries (kind `live`)

| Slug | Price (per 1M tokens, verified 2026-10-13) | Notes |
|---|---|---|
| `openai/gpt-realtime-2.1` | audio in $32 (cached $0.40) · audio out $64 · text in $4 (cached $0.40) · text out $24 · image in $5 | latest GA |
| `openai/gpt-realtime-2.1-mini` | audio in $10 (cached $0.30) · out $20 · text in $0.60 (cached $0.06) · out $2.40 · image $0.80 | cheap default |
| `openai/gpt-realtime` (+ `-mini`, `-1.5`, `-2`) | as listed on pricing page | include for SDK defaults that still send `gpt-realtime` |
| `gemini/gemini-3.8-live` | text in $0.75 · audio/video in $3.00 · text out $4.50 · audio out $12.00 | GA 2026-09-15 |
| `gemini/gemini-3.8-live-extended-thinking` | same | |
| `gemini/gemini-2.5-flash-native-audio-preview-12-2025` (optional) | text in $0.50 · audio in $3.00 · text out $2.00 · audio out $12.00 | legacy |

- `modes: ["live"]`. Capabilities: `input_encodings`/`output_encodings` (OpenAI pcm16 24k,
  g711 µ/A; Gemini in pcm16 16k, out pcm16 24k), `voices`, `tools: true`, `max_session_seconds`.
- New catalog field `dialect: "openai-realtime" | "gemini-live"` tells clients which SDK to use.
- **Not in scope, but noted:** OpenAI's `gpt-live-1` ($0.05/min plus backend usage) is a
  different, per-minute product. Revisit separately.

### 2.8 Rollout safety
- `enable_live=false` by default in cloud until cloud billing is deployed.
- `max_concurrent_live` per org, default 5.
- **The house-key exposure is large** (gpt-realtime audio out $64/1M). Consider live requiring a
  positive balance above a threshold, e.g. ≥ $5 (`speechrouter:balance`), at admission, not just
  "not blocked". See Q7.

---

## 3. What cloud (Rails) needs, for the follow-up session

### 3.0 Usage event schema — AUTHORITATIVE (v2, as implemented in the gateway)
> Added during implementation (2026-10-13). This pins down what §1.4/§1.5/§2.6 describe.
> Additive only: every v1 field keeps its meaning, so an STT event is unchanged except for
> the new fields at their defaults.

Each `XADD speechrouter:usage` entry is `{"payload": <JSON>}` with these fields:

| field | type | v1? | meaning |
|---|---|---|---|
| `session_id` | string | yes | **Idempotency key, unique per event.** STT: `sess_…` / `batch_…` / `dg_…`. TTS: `tts_…` (REST) or `speak_…` (WS). Live: `<parent_session_id>:<seq>` (e.g. `live_ab12…:3`). |
| `key_id` | string | yes | API key id (never the key) |
| `model` | string | yes | resolved slug, e.g. `openai/gpt-4o-mini-tts`, `gemini/gemini-3.8-live` |
| `kind` | string | yes | `stt_stream` \| `stt_batch` \| `tts_batch` (POST /v1/audio/speech) \| `tts_stream` (WSS /v1/speak) \| `live` |
| `audio_seconds` | float | yes | STT: audio transcribed. **TTS: audio generated.** Live: audio *input* relayed client→provider during this event's interval |
| `billed_seconds` | float | yes | STT only (seconds-priced). `0` for TTS and live |
| `billing_basis` | string | yes | `audio_time` \| `session_time` \| **`units`** (new: price from `units`) |
| `characters` | int | yes | TTS: Unicode code points sent upstream. `0` otherwise. Can exceed int4 in aggregate only; per event ≤ ~10⁶ |
| `provider_switches` | int | yes | STT failover count; `0` for TTS/live |
| `status` | string | yes | `completed` \| `client_disconnect` \| `provider_error` \| `error` \| `insufficient_credits` \| `session_expired` \| `audio_timeout` \| **`in_progress`** (new: a live checkpoint; more events follow for the same parent) |
| `byok` | bool | yes | org's own provider key → routing fee only |
| `ts` | float | yes | unix seconds at emit |
| `units` | object `{string: number}` | **new** | Priced quantities as raw counts for this event. Keys (closed set, additions allowed): `characters`, `text_input_tokens`, `cached_text_input_tokens`, `audio_input_tokens`, `cached_audio_input_tokens`, `image_input_tokens`, `text_output_tokens`, `audio_output_tokens`. Empty `{}` for STT. Cached counts are NOT included in the uncached key (OpenAI `cached_tokens` is subtracted out). |
| `units_estimated` | bool | **new** | `true` when the provider sent no usage and the gateway estimated tokens from relayed audio |
| `parent_session_id` | string \| null | **new** | Live only: the session all checkpoint events roll up to. `null` for STT/TTS |
| `session_seconds` | float | **new** | Wall-clock seconds covered by this event (live: the checkpoint interval; TTS/STT: request/session duration) |
| `output_audio_seconds` | float | **new** | Audio generated: TTS = same as `audio_seconds`; live = provider→client audio in this interval |
| `list_cost_usd` | float | **new** | Gateway's own Σ units × catalog rate (cross-check only; cloud prices from its table). `0` for BYOK and STT |

**Pricing rule:** `price = Σ_k units[k] × rate(k)`. Rate fields in the catalog `pricing` object:
`characters → per_character_usd` (per 1 char); every `*_tokens` key → `per_1m_<key>_usd` per 1,000,000
(e.g. `audio_output_tokens → per_1m_audio_output_tokens_usd`). A unit with no rate field on the
model costs 0 (e.g. OpenAI `tts-1` has only `per_character_usd`).

**Dated prices:** catalog entries may carry
`"pricing_schedule": [{"effective_from": "2027-01-01", "pricing": {…full rate set…}}]`. The rate set in
force at event `ts` is the latest schedule entry with `effective_from <= date(ts)` (UTC), else `pricing`.
`GET /v1/models` serves `pricing` as the rate set in force *now*, with the schedule alongside.

**Live checkpoints:** every 60 s of a live session the gateway emits one event with
`status = "in_progress"` and the *delta* units/seconds since the previous event. At close it emits a final
event with the terminal status. `seq` starts at 1 and increments, with no gaps. A session that ends inside
its first 60 s emits exactly one event (`<parent>:1`). Sum all events per `parent_session_id` for totals.

**OpenAI input-transcription legs (added 2026-10-13, resolves Q4 without new fields):** when an
OpenAI Realtime session has input transcription enabled (`session.audio.input.transcription.model`),
OpenAI bills that transcription separately at the transcription model's rate. The gateway emits, next
to each live event that covers transcribed audio, one companion event:
`kind = "stt_stream"`, `model = "openai/<transcription model>"` (e.g. `openai/gpt-4o-mini-transcribe`),
`session_id = "<parent>:t<n>"` (own counter, from 1, no gaps), `parent_session_id = <parent>`,
`billing_basis = "audio_time"`, `audio_seconds = billed_seconds =` input audio relayed while
transcription was on, `units = {}`, same `status` as the live event it accompanies. Cloud prices it
with the **existing seconds path** (the STT catalog rate for that slug). Totals per live session =
all events with that `parent_session_id`, both kinds.

**Live status values:** besides `in_progress`/`completed`/`client_disconnect`, a final live event may
be `provider_error` (upstream refused or dropped), `error` (client protocol violation, e.g. a second
Gemini `setup`), or a limit status (`insufficient_credits`, `session_expired`, `audio_timeout`). A
session refused at upstream handshake still emits exactly one final event (`<parent>:1`, empty units).

**Gateway ↔ cloud Redis/HTTP contract additions (2026-10-13, agreed with SRC-TTS-LIVE):**
- `speechrouter:live_min_balance` (micro-USD, written by cloud): live admission floor for house-key
  sessions, compared against `speechrouter:balance:<org>`. Absent → the gateway's
  `SPEECHROUTER_LIVE_MIN_BALANCE_MICROUSD` (default 5_000_000). BYOK sessions skip the floor.
- `GET /v1/models?include_disabled=true` returns flag-gated kinds too, each marked `"enabled": false`,
  so `sync_models` can price TTS/live **before** the flags flip. The default `/v1/models` keeps hiding them,
  and disabled models stay unroutable (`model_not_found`).
- Browser auth on **both** live paths (`/v1/realtime`, `/v1/live/gemini` and the BidiGenerateContent paths)
  accepts the `bearer, <key>` subprotocol.
- Live mid-session credit check subtracts only cost **not yet emitted** (emitted checkpoints are assumed
  debited into `speechrouter:balance`).

**Catalog fields cloud should read:** `kind` (`stt`|`tts`|`live`), `modes` (`streaming`|`batch`|`live`),
`dialect` (live only: `openai-realtime`|`gemini-live`), `pricing`, `pricing_schedule`. For multi-rate
entries `pricing.per_second_usd` is **not** derived: treat it as absent.

Ordered by dependency. **Items 1–4 must deploy before the gateway flags flip in prod.**

1. **Pricing model.** Replace the single rate per slug with multiple rates:
   - Add `model_prices.rates jsonb` (`{"text_input_tokens": micro-USD per 1M, ...,
     "characters": micro-USD per char}`), or a child table `model_price_components(slug, unit,
     per_unit_microusd)`. Keep `unit`/`per_unit_microusd` for existing STT rows.
   - Add a `kind` column (`stt|tts|live`) and support `effective_from` (Gemini TTS price step on
     2027-01-01).
2. **`sync_models` rake.** Read the new `per_character_usd` and `per_1m_*_tokens_usd` fields plus
   `kind`/`modes`/`dialect`. **Stop silently skipping**: fail loudly or alert on any catalog
   entry with no recognized rate. Mark removed slugs `active: false`.
3. **`UsageConsumerJob`.**
   - Price from `units` as Σ units × rate when present; fall back to the seconds path for STT.
   - Store the gateway's `list_cost_usd` and alert when it differs from cloud's price by more
     than 1%.
   - Handle `parent_session_id` checkpoint events (each with a unique `session_id`, so the
     existing idempotency holds).
   - **Dead-letter instead of halting:** rescue per entry, move it to a
     `speechrouter:usage:dead` stream or a DB table, ack, alert. This fixes the existing "poison
     event stops all billing" bug, which gets riskier with richer payloads.
   - Never leave an event with `price_microusd = nil` silently: alert on every unpriced,
     non-BYOK event.
4. **`usage_events` schema.**
   - Add `units jsonb`, `units_estimated boolean`, `parent_session_id`, `session_seconds`,
     `output_audio_seconds`, `list_cost_microusd`.
   - Widen `characters` to bigint.
   - Index `(org_id, kind, created_at)`.
5. **Balance sync.** Mid-session cuts depend on `speechrouter:balance:<org>`, so it must update
   from checkpoint events (it already updates after each debit). Optional: a
   `speechrouter:live_min_balance` setting.
6. **Dashboard** (`DashboardController`, `Dashboard.tsx`):
   - Split tiles: "Audio transcribed", "Speech generated (chars / minutes)", "Live minutes".
   - Stop adding TTS output into "Audio routed".
7. **Logs** (`LogsController`, `Logs.tsx`):
   - Kind filter becomes `stt_stream, stt_batch, tts_batch, tts_stream, live`.
   - Columns show characters, tokens and session minutes per kind.
   - Group checkpoints under the parent session.
8. **Models page** (`Models.tsx`, `ModelsController`):
   - Kind tabs (STT / TTS / Live) and price rendering for per-character and per-token rates
     (per-minute equivalents where the provider publishes them, e.g. Gemini Live $0.005/min in,
     $0.018/min out).
   - Remove the hardcoded "Coming soon · TTS" list for slugs now in the catalog (it auto-drops
     when present; check `openai/tts` vs the real slugs).
   - Update the meta description beyond "speech-to-text".
9. **Playground** (`Playground.tsx`):
   - Filter the catalog by `kind`; today TTS models would appear as transcription options.
   - Add a **TTS tab** (text + voice + format, which plays `POST /v1/audio/speech`).
   - Add a **Live tab** (mic ↔ `/v1/realtime` via a minted `st_` token, with transcripts and
     audio playback). Keep it OpenAI-first; Gemini second.
10. **Keys page quickstarts:** add TTS (curl `/v1/audio/speech`, OpenAI SDK) and live (OpenAI
    SDK realtime with base_url; google-genai with `http_options`) snippets.
11. **BYOK:** `openai` and `gemini` are already in `ByokCredential::PROVIDERS`, so nothing is
    needed for this ticket. Update the OrgSettings copy ("Cloud STT only" → STT/TTS/live).
    Phase 2 TTS providers are already listed too, except Azure, which is multi-field.
12. **Admin (Avo):** surface units/kind on the usage event resource.
13. **Tests:** extend `test/jobs/usage_consumer_job_test.rb` with tts (chars), tts (tokens),
    live (multi-component + checkpoints), unpriced → alert, poison → dead-letter. Add
    `sync_models` tests for the new fields.
14. **API docs:** live in **this** repo's `docs-site/` (Starlight), not in cloud. See §4.

---

## 4. Files to touch, tests, sequencing, estimate

### 4.1 Gateway / repo files
**Spec and codegen**
- `packages/spec/catalog.schema.json`: `kind` + `live`, `modes` + `live`, multi-rate token
  pricing fields and effective dates, `dialect`, TTS caps (`formats`, `default_voice`,
  `max_input_chars`, `instructions`, `speed`).
- `packages/spec/events.schema.json`: `Done.usage` + `units`; `SessionOpen` + `voice` for
  `/v1/speak`; no other protocol changes. Then run `scripts/codegen.sh`, which updates
  `gateway/speechrouter_gateway/protocol/events.py`.
- `packages/spec/openapi.yaml`: `POST /v1/audio/speech`, `POST /v1/realtime/client_secrets`,
  WS docs for `/v1/speak`, `/v1/realtime` and the Gemini path.

**Core**
- `providers/base.py`: `TTSCapabilities`, `TTSConfig`, `TTSUsage`, `TTSProvider`.
- `providers/registry.py`: `register_tts` and `tts_provider`.
- `router/resolver.py`: `resolve_tts`, `resolve_live`, and the `kind` guard in the STT resolvers.
- `router/catalog.py`: no legacy `per_second_usd` for multi-rate entries; filter by enabled
  kinds; `price_units()` helper for cost computation.
- `router/limits.py`: no change; a live scope key is enough.
- `metering/emitter.py`: `units`, `units_estimated`, `parent_session_id`, `session_seconds`,
  `list_cost_usd`, and `kind` + `live`.
- `config.py`: `enable_tts`, `enable_live`, `max_tts_input_chars`, `max_concurrent_live`,
  `max_live_session_seconds`, `live_idle_timeout_seconds`.
- `main.py`: include the new routers.

**New**
- `api/speech.py` (`POST /v1/audio/speech`).
- `api/speak_ws.py` (`WSS /v1/speak`).
- `tts/segmenter.py`, `tts/session.py` (the speak session: segment pipeline, clear, seq).
- `audio/wav.py`, `audio/g711.py` (format wrappers).
- `providers/openai/tts.py` + `providers/openai/models.json` (TTS and live entries).
- `providers/gemini/tts.py` + `providers/gemini/models.json`.
- `api/realtime_ws.py` (OpenAI dialect + Gemini dialect routes).
- `live/proxy.py` (pumps, watchdog, teardown), `live/meter.py` (per-dialect usage extractors,
  fallback estimators, checkpoint emitter), `live/dialects.py` (auth extraction, model
  extraction, error shaping per dialect).
- `api/tokens.py`: add the `/v1/realtime/client_secrets` alias.

**Docs and SDKs**
- `docs/providers/openai.md`, `docs/providers/gemini.md`: TTS and live protocol facts sections.
- `docs-site/src/content/docs/`:
  - new `guides/tts.md`, `guides/live.md`, `recipes/voice-agent.md` (update)
  - `reference/rest.md`, `reference/events.md`, `guides/pricing.md`
  - `providers/openai.md`, `providers/gemini.md`
- `packages/sdk-python/speechrouter/`: `client.speech()` and `speak()` WS helper.
  `packages/sdk-ts/src/`: `speak.ts`. Live uses the vendor SDKs, so only a docs snippet plus
  a token helper is needed.
- `scripts/`: `openai_tts_probe.py`, `gemini_tts_probe.py`, and extend `gemini_probe.py` /
  add `realtime_probe.py`. These capture real frames as test fixtures, as was done for STT.
- `README.md`, `CONTRIBUTING.md`: mention TTS and live adapters.

### 4.2 Test strategy
- **Unit, fixture-driven, no network** (the repo's existing style, e.g. `test_gemini_adapter.py`).
  Fixtures are real frames captured by the probe scripts:
  - OpenAI TTS SSE parsing and usage.
  - Gemini `streamGenerateContent` chunk parsing and `usageMetadata`.
  - WAV header streaming and G.711 tables (against known vectors).
  - Segmenter boundaries, CJK, max-wait, and `clear` mid-segment.
  - `resolve_tts`/`resolve_live` validation matrix: kind mismatch, bad voice/format, missing creds.
  - Cost computation from units, and catalog legacy-pricing suppression.
- **API tests with `TestClient`** (as `test_batch.py`/`test_dg_compat.py` do), with
  `httpx.MockTransport` for upstream TTS:
  - streaming body and headers, error envelope, usage event emitted once with correct units
    on success, provider error and client abort;
  - BYOK flagging, `org_blocked` → 402, flag off → 404.
- **Live proxy tests** against an **in-process fake upstream WS server**
  (`websockets.serve` on localhost) scripted per dialect:
  - frames forwarded verbatim both ways, including binary;
  - credentials stripped (the fake server asserts it gets the house key, never the client's);
  - Gemini first-frame model extraction;
  - usage summed across `response.done` and cumulative vs per-turn `usageMetadata`;
  - checkpoint cadence (patched clock), mid-session credit cut, max-duration, idle;
  - upstream close-code propagation, and client disconnect → upstream closed;
  - concurrency slot released on every path (the `test_limits.py` pattern).
- **Live smoke tests** (manual, opt-in, need keys, never in CI): the probe scripts, plus one
  end-to-end through a local gateway with the official OpenAI SDK and `google-genai` pointed at
  `localhost`. **Budget: about $2–5 of provider spend total.**
- CI gates unchanged: `ruff`, `pyright`, `pytest`, and spec drift.

### 4.3 Suggested PR sequence (each one reviewable)

| PR | Content | Gateway LOC (code + tests) |
|---|---|---|
| 1 | Spec + catalog multi-rate pricing + `UsageEvent.units` + kind guards + flags (no new endpoints) | ~400 |
| 2 | `POST /v1/audio/speech` + OpenAI & Gemini TTS adapters + wav/g711 + probes + docs | ~1,100 |
| 3 | `WSS /v1/speak` (segmenter session) + SDK helpers | ~800 |
| 4 | Live proxy core + OpenAI Realtime dialect + client_secrets alias + docs | ~1,200 |
| 5 | Gemini Live dialect (first-frame model, Gemini auth forms, usageMetadata) | ~500 |
| cloud | Items 1–5 & 13 (billing) first, then 6–12 (UI) | ~1,200–1,800 Rails + TSX |

**Total:** about 4,000 LOC in the gateway, spec, docs and SDK, plus 1,500 in cloud.

**Rough effort/cost:**
- Gateway is about 4–6 focused agent sessions (one per PR, plus review rounds), roughly 3–5
  engineer-days equivalent.
- Cloud is 2–3 sessions.
- Provider spend for verification is under $5.
- No AWS or other infrastructure is needed; nothing new to provision.

**Ongoing risk:** house-key exposure on live, mitigated by §2.8 limits.

---

## 5. Open questions (need a human decision)

1. **Live protocol:** OK to ship **provider-native passthrough** first (recommended) and defer
   a normalized `/v1/agent` protocol? Or is cross-provider normalization a launch requirement?
2. **Which TTS models at launch:** all of the §1.3 set, or only `openai/gpt-4o-mini-tts` +
   `gemini/gemini-3.8-flash-tts`? Pull ElevenLabs/Cartesia/Deepgram (Phase 2) into this effort?
3. **Ephemeral tokens for live:** should `st_` tokens be able to **pin** session config (model,
   instructions, tools), as OpenAI client secrets can? That would add a token payload field.
4. **Billing granularity:** charge pure pass-through per token component (recommended,
   consistent with "exactly what we charge"), or convert to a simplified per-minute live price
   for customers? How should the OpenAI input-transcription sub-charge appear?
5. **Checkpoint usage events** (unique `session_id` per 60 s delta, plus `parent_session_id`):
   acceptable to cloud? Or should cloud move to `(session_id, seq)` idempotency?
6. **Gemini TTS price step on 2027-01-01:** support dated prices in the catalog, or just
   schedule a catalog bump PR?
7. **Live admission:** require a minimum balance (e.g. $5) beyond "not blocked"? What default
   `max_concurrent_live`?
8. **Audio persistence (`audio_sink`)** for TTS/live: out of scope for v1, OK? It would need
   base64 decode in the proxy and HIPAA review of storing model output.
9. **TTS failover** (pre-first-byte retry on a fallback model, which changes the voice): want it?
10. **Rate limits:** per-org TTS RPS limit beyond concurrency?

## 6. Missing access / prerequisites
- **No provider keys on this server:** `SPEECHROUTER_OPENAI_API_KEY` and
  `SPEECHROUTER_GEMINI_API_KEY` (and their unprefixed variants) are unset, and the worktree has
  only `deploy/.env.example`. The probes and live smoke tests need an OpenAI key with
  realtime + TTS access and a Gemini API key on a **paid tier**: free-tier traffic may be used
  for training, which is not acceptable for real usage, though fine for fixture capture with
  synthetic text. Fixture capture must use synthetic text/audio only.
- The cloud repo was surveyed read-only via `gh`. Implementing cloud changes needs the cloud
  session's own worktree.
- Pricing was verified on 2026-10-13 against developers.openai.com/api/docs/pricing and
  ai.google.dev/gemini-api/docs/pricing. **Re-check at implementation time.** The voice lists
  and some wire details (OpenAI audio tokens/sec, Gemini Live `usageMetadata` semantics) are
  unverified until probed.
