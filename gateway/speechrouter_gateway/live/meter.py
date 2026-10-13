"""Usage metering for live passthrough sessions (PLAN §2.6).

The proxy forwards frames verbatim and hands each one to the meter, which
reads only what billing needs:

- provider-reported token usage (OpenAI `response.done.response.usage`,
  Gemini `usageMetadata`) -> cumulative UsageEvent.units totals;
- base64 audio lengths in both directions -> audio seconds (no decoding:
  the byte count is derived from the base64 length);
- OpenAI only: the input-transcription model from session.created/updated,
  so its separately billed transcription is metered as an STT leg.

If a session ends without the provider ever reporting usage, the final
event carries an estimate from relayed audio (units_estimated=true).
Checkpoints never estimate, so a late report can't be double counted.
"""

import json
import math
from dataclasses import dataclass, field


def b64_len(data: str) -> int:
    """Decoded byte length of a base64 string, without decoding it."""
    if not data:
        return 0
    return len(data) * 3 // 4 - data[-2:].count("=")


def parse_frame(frame: str | bytes) -> dict | None:
    """Gemini sends JSON in BINARY frames; OpenAI in text. Try both."""
    try:
        payload = json.loads(frame)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass
class LiveTotals:
    units: dict[str, float] = field(default_factory=dict)
    audio_in_seconds: float = 0.0
    audio_out_seconds: float = 0.0
    transcribed_seconds: float = 0.0  # input audio while transcription was on

    def copy(self) -> "LiveTotals":
        return LiveTotals(dict(self.units), self.audio_in_seconds, self.audio_out_seconds,
                          self.transcribed_seconds)

    def minus(self, other: "LiveTotals") -> "LiveTotals":
        keys = set(self.units) | set(other.units)
        units = {k: self.units.get(k, 0.0) - other.units.get(k, 0.0) for k in keys}
        return LiveTotals(
            {k: v for k, v in units.items() if v},
            self.audio_in_seconds - other.audio_in_seconds,
            self.audio_out_seconds - other.audio_out_seconds,
            self.transcribed_seconds - other.transcribed_seconds,
        )


def _add(units: dict[str, float], key: str, value) -> None:
    if isinstance(value, (int, float)) and value > 0:
        units[key] = units.get(key, 0.0) + float(value)


class LiveMeter:
    """Base: subclasses implement on_client / on_server per dialect."""

    # fallback estimate rates (tokens per second of audio), per direction
    est_in_tokens_per_second: float = 0.0
    est_out_tokens_per_second: float = 0.0

    def __init__(self) -> None:
        self.totals = LiveTotals()
        self.reported = False  # provider ever sent usage this session
        self.transcription_model: str | None = None

    def on_client(self, frame: str | bytes) -> str | None:
        """Inspect a client->provider frame. Returns a rejection message when
        the gateway must NOT forward it (policy), else None."""
        return None

    def on_server(self, frame: str | bytes) -> None:
        """Inspect a provider->client frame."""

    def estimate(self) -> dict[str, float]:
        t = self.totals
        units: dict[str, float] = {}
        _add(units, "audio_input_tokens",
             math.ceil(t.audio_in_seconds * self.est_in_tokens_per_second))
        _add(units, "audio_output_tokens",
             math.ceil(t.audio_out_seconds * self.est_out_tokens_per_second))
        return units


# ------------------------------------------------------------------ OpenAI

_OPENAI_RATES = {"audio/pcm": 24000, "pcm16": 24000, "audio/pcmu": 8000, "g711_ulaw": 8000,
                 "audio/pcma": 8000, "g711_alaw": 8000}


def _openai_seconds(byte_count: int, rate: int) -> float:
    width = 1 if rate == 8000 else 2  # G.711 = 1 byte/sample, pcm16 = 2
    return byte_count / (width * rate)


class OpenAIRealtimeMeter(LiveMeter):
    """Reads GA shapes (`session.audio.input.format`, `response.output_audio
    .delta`) and the beta ones (`input_audio_format`, `response.audio.delta`)
    so older SDKs meter correctly.

    Estimate rates are NOT published by OpenAI; these follow the commonly
    cited 1 token / 100 ms in and 1 token / 50 ms out. Unverified — they only
    matter when a session reports no usage at all.
    """

    est_in_tokens_per_second = 10.0
    est_out_tokens_per_second = 20.0

    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model
        self.in_rate = 24000
        self.out_rate = 24000

    def on_client(self, frame: str | bytes) -> str | None:
        if isinstance(frame, bytes):
            return None
        payload = parse_frame(frame)
        if payload is None:
            return None
        kind = payload.get("type")
        if kind == "input_audio_buffer.append":
            seconds = _openai_seconds(b64_len(payload.get("audio") or ""), self.in_rate)
            self.totals.audio_in_seconds += seconds
            if self.transcription_model:
                self.totals.transcribed_seconds += seconds
        elif kind == "session.update":
            requested = (payload.get("session") or {}).get("model")
            if requested and requested != self.model:
                return (f"session model is fixed by the connection URL ('{self.model}'); "
                        f"open a new connection for '{requested}'")
        return None

    def on_server(self, frame: str | bytes) -> None:
        payload = parse_frame(frame)
        if payload is None:
            return
        kind = payload.get("type")
        if kind in ("response.output_audio.delta", "response.audio.delta"):
            self.totals.audio_out_seconds += _openai_seconds(
                b64_len(payload.get("delta") or ""), self.out_rate)
        elif kind == "response.done":
            usage = (payload.get("response") or {}).get("usage")
            if isinstance(usage, dict):
                self.reported = True
                for key, value in openai_units(usage).items():
                    _add(self.totals.units, key, value)
        elif kind in ("session.created", "session.updated"):
            self._read_session(payload.get("session") or {})

    def _read_session(self, session: dict) -> None:
        audio = session.get("audio") or {}
        in_cfg = audio.get("input") or {}
        out_cfg = audio.get("output") or {}
        in_fmt = (in_cfg.get("format") or {}).get("type") or session.get("input_audio_format")
        out_fmt = (out_cfg.get("format") or {}).get("type") or session.get("output_audio_format")
        self.in_rate = _OPENAI_RATES.get(in_fmt or "", self.in_rate)
        self.out_rate = _OPENAI_RATES.get(out_fmt or "", self.out_rate)
        transcription = in_cfg.get("transcription") or session.get("input_audio_transcription")
        self.transcription_model = (
            transcription.get("model") if isinstance(transcription, dict) else None
        )


def openai_units(usage: dict) -> dict[str, float]:
    """response.usage -> units. Cached tokens are split OUT of the uncached
    keys (OpenAI reports them as a subset of input)."""
    inp = usage.get("input_token_details") or {}
    out = usage.get("output_token_details") or {}
    cached = inp.get("cached_tokens_details") or {}
    cached_text = cached.get("text_tokens") or 0
    cached_audio = cached.get("audio_tokens") or 0
    units: dict[str, float] = {}
    _add(units, "text_input_tokens", (inp.get("text_tokens") or 0) - cached_text)
    _add(units, "cached_text_input_tokens", cached_text)
    _add(units, "audio_input_tokens", (inp.get("audio_tokens") or 0) - cached_audio)
    _add(units, "cached_audio_input_tokens", cached_audio)
    _add(units, "image_input_tokens", inp.get("image_tokens"))
    _add(units, "text_output_tokens", out.get("text_tokens"))
    _add(units, "audio_output_tokens", out.get("audio_tokens"))
    return units


# ------------------------------------------------------------------ Gemini


def _mime_rate(mime: str, default: int) -> int:
    for part in mime.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "rate" and value.isdigit():
            return int(value)
    return default


_PROMPT_KEYS = {"TEXT": "text_input_tokens", "AUDIO": "audio_input_tokens",
                "IMAGE": "image_input_tokens", "VIDEO": "image_input_tokens"}
_CACHED_KEYS = {"TEXT": "cached_text_input_tokens", "AUDIO": "cached_audio_input_tokens"}
_RESPONSE_KEYS = {"TEXT": "text_output_tokens", "AUDIO": "audio_output_tokens"}


class GeminiLiveMeter(LiveMeter):
    """usageMetadata semantics on Live are UNVERIFIED (docs/providers/
    gemini.md): `per_message` (default) sums every report, right if each
    message bills its own turn, which is how Live bills context per turn;
    `cumulative` keeps the largest running total, right if each message
    restates the session so far. scripts/tts_live_probe.py (gemini_live) captures the evidence.

    Estimate rates come from Google's published per-minute prices for
    gemini-3.8-live: $0.005/min in at $3/1M = 1667 tok/min; $0.018/min out
    at $12/1M = 1500 tok/min (25/s).
    """

    est_in_tokens_per_second = 1667 / 60
    est_out_tokens_per_second = 25.0

    def __init__(self, semantics: str = "per_message") -> None:
        super().__init__()
        self._semantics = semantics
        self._setup_seen = False
        self.split_guessed = False  # usage arrived without a modality breakdown

    def on_client(self, frame: str | bytes) -> str | None:
        payload = parse_frame(frame)
        if payload is None:
            return None
        if "setup" in payload:
            if self._setup_seen:
                return "setup may only be sent once per connection"
            self._setup_seen = True
            return None
        realtime = payload.get("realtimeInput") or payload.get("realtime_input")
        if isinstance(realtime, dict):
            chunks = [realtime["audio"]] if isinstance(realtime.get("audio"), dict) else []
            chunks += [c for c in realtime.get("mediaChunks") or [] if isinstance(c, dict)]
            for chunk in chunks:
                mime = chunk.get("mimeType") or chunk.get("mime_type") or ""
                if mime.startswith("audio/"):
                    self.totals.audio_in_seconds += b64_len(chunk.get("data") or "") / (
                        2 * _mime_rate(mime, 16000))
        return None

    def on_server(self, frame: str | bytes) -> None:
        payload = parse_frame(frame)
        if payload is None:
            return
        content = payload.get("serverContent") or {}
        for part in (content.get("modelTurn") or {}).get("parts") or []:
            inline = part.get("inlineData") or {}
            mime = inline.get("mimeType") or ""
            if mime.startswith("audio/"):
                self.totals.audio_out_seconds += b64_len(inline.get("data") or "") / (
                    2 * _mime_rate(mime, 24000))
        meta = payload.get("usageMetadata")
        if isinstance(meta, dict):
            self.reported = True
            units = self.gemini_units(meta)
            if self._semantics == "cumulative":
                for key, value in units.items():
                    self.totals.units[key] = max(self.totals.units.get(key, 0.0), value)
            else:
                for key, value in units.items():
                    _add(self.totals.units, key, value)

    def gemini_units(self, meta: dict) -> dict[str, float]:
        units: dict[str, float] = {}
        cached = {d.get("modality"): d.get("tokenCount") or 0
                  for d in meta.get("cacheTokensDetails") or []}
        for modality, count in cached.items():
            key = _CACHED_KEYS.get(modality or "")
            if key:
                _add(units, key, count)
        prompt = meta.get("promptTokensDetails") or []
        for detail in prompt:
            modality = detail.get("modality", "")
            key = _PROMPT_KEYS.get(modality)
            if key:
                _add(units, key, (detail.get("tokenCount") or 0) - cached.get(modality, 0))
        if not prompt and meta.get("promptTokenCount"):
            # no modality split: native-audio sessions are audio-dominated
            _add(units, "audio_input_tokens", meta["promptTokenCount"])
            self.split_guessed = True
        response = meta.get("responseTokensDetails") or []
        for detail in response:
            key = _RESPONSE_KEYS.get(detail.get("modality", ""))
            if key:
                _add(units, key, detail.get("tokenCount"))
        if not response and meta.get("responseTokenCount"):
            _add(units, "audio_output_tokens", meta["responseTokenCount"])
            self.split_guessed = True
        _add(units, "text_input_tokens", meta.get("toolUsePromptTokenCount"))
        _add(units, "text_output_tokens", meta.get("thoughtsTokenCount"))
        return units
