"""xAI Grok Voice Transcribe streaming adapter (raw WebSocket, /v1/stt).

Protocol notes and the open questions behind the choices here:
docs/providers/xai.md (written from docs.x.ai speech-to-text guide, the
stt-streaming.ws.json schema and xAI's Rust client, 2026-09-23).

- Auth is the `Authorization: Bearer` header on the upgrade; a bad key is an
  HTTP status before 101. All session config rides in query params.
- connect() returns after `transcript.created`: the server initializes its
  ASR backend first and audio sent before it is not guaranteed to land.
- Audio is raw binary frames: pcm (s16le), mulaw or alaw. Opus is not
  offered: it needs exactly one packet per frame, which a ring-buffer replay
  cannot preserve.
- Every `transcript.partial` carries `is_final` and `speech_final`:
  interim (false/false), chunk final (true/false, ~3 s of locked text) and
  utterance final (true/true, documented as the "complete stitched
  utterance"). Chunk finals go out as interims and only `speech_final`
  becomes a final, the reading xAI's own client uses. Whether later events
  repeat the locked text or carry only the tail is undocumented, so
  UtteranceState decides per event from `start`: an event starting where
  the utterance started is cumulative, one starting at or after the locked
  text's end is a tail and gets the locked text prepended. Either way no
  words are lost at chunk boundaries and none are sent twice.
- End of input is `{"type": "audio.done"}`; the server flushes, sends
  `transcript.done` and closes. Whether its text is the whole session or
  only the flushed tail is undocumented, so only its words past the last
  final are surfaced (see UtteranceState.done).
- `error` frames carry only a message. Parse errors keep the socket open;
  everything else closes it. Close codes are undocumented, so a close after
  an error is treated as recoverable and left to failover.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import Transcript, UtteranceEnd, Word
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream
from ..wsconnect import ws_connect

WS_URL = "wss://api.x.ai/v1/stt"

# xAI's own client waits 10 s for `transcript.created`.
READY_TIMEOUT = 15.0

_ENCODINGS = {"linear16": "pcm", "mulaw": "mulaw", "alaw": "alaw"}
SAMPLE_RATES = frozenset({8000, 16000, 22050, 24000, 44100, 48000})

# The 25 codes whose `language` enables formatting. The model transcribes
# all of them regardless; `language` only switches on ITN.
LANGUAGES = frozenset({
    "ar", "cs", "da", "de", "en", "es", "fa", "fil", "fr", "hi", "id", "it", "ja",
    "ko", "mk", "ms", "nl", "pl", "pt", "ro", "ru", "sv", "th", "tr", "vi",
})

# Query params the adapter owns; provider_params cannot override them.
# multichannel changes the event shape (channel_index, one done per channel).
RESERVED_PARAMS = frozenset({"model", "encoding", "sample_rate", "channels", "multichannel"})

# Events report seconds to 2 d.p.
_EPS = 0.02

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,
    endpointing=True,  # speech_final after `endpointing` ms of silence (default 400)
    keyterms=True,
    keyterms_max=100,
    languages=frozenset({"auto", *LANGUAGES}),
    encodings=frozenset(_ENCODINGS),
    sample_rates=SAMPLE_RATES,
)


def vendor_model(model: str) -> str:
    """Batch has its own slug for its own price; xAI's model id is the same."""
    return model.removesuffix("-batch")


def api_language(language: str | None) -> str | None:
    """Bare primary subtag; `auto` means leave it unset (xAI rejects `auto`)."""
    if not language or language == "auto":
        return None
    return language.split("-", 1)[0].lower()


def _param_value(value) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def build_url(config: STTConfig, base: str = WS_URL) -> str:
    """Raises on audio or a model the socket cannot carry."""
    if config.model.endswith("-batch"):
        raise ProviderStreamError(
            f"xai/{config.model} is batch-only; stream with "
            f"xai/{vendor_model(config.model)}",
            recoverable=False, provider="xai", code="invalid_request",
        )
    encoding = _ENCODINGS.get(config.encoding)
    if encoding is None or config.channels != 1:
        raise ProviderStreamError(
            "xai streaming accepts mono linear16, mulaw or alaw "
            f"(got {config.encoding}, {config.channels} channel(s))",
            recoverable=False, provider="xai", code="invalid_request",
        )
    if config.sample_rate not in SAMPLE_RATES:
        raise ProviderStreamError(
            f"xai streaming accepts sample_rate {', '.join(map(str, sorted(SAMPLE_RATES)))} "
            f"(got {config.sample_rate})",
            recoverable=False, provider="xai", code="invalid_request",
        )
    params: list[tuple[str, str]] = [
        ("model", config.model),
        ("encoding", encoding),
        ("sample_rate", str(config.sample_rate)),
        ("interim_results", _param_value(config.interim_results)),
    ]
    language = api_language(config.language)
    if language:
        params.append(("language", language))
    if config.diarization:
        params.append(("diarize", "true"))
    params.extend(("keyterm", term) for term in config.keyterms)
    for key, value in config.provider_params.items():
        if key in RESERVED_PARAMS:
            logger.warning(
                "xai provider_params key is reserved by the adapter; ignored",
                extra={"provider": "xai", "param": key},
            )
            continue
        for item in value if isinstance(value, (list, tuple)) else [value]:
            params.append((key, _param_value(item)))
    return f"{base}?{urlencode(params)}"


def parse_words(raw_words, offset: float = 0.0) -> list[Word]:
    words: list[Word] = []
    for w in raw_words or []:
        if w.get("start") is None or w.get("end") is None:
            continue
        conf = w.get("confidence")  # omitted when 0
        speaker = w.get("speaker")
        words.append(Word(
            w=w.get("text", ""),
            start=offset + float(w["start"]),
            end=offset + float(w["end"]),
            conf=float(conf) if isinstance(conf, (int, float)) else None,
            speaker=speaker if isinstance(speaker, int) else None,
        ))
    return words


def _stream_words(msg: dict, start: float) -> list[Word]:
    """Words should be stream-absolute like `start`. Absolute words can never
    precede the event that carries them, so words that do are shifted."""
    words = parse_words(msg.get("words"))
    if words and start > _EPS and words[0].start < start - _EPS:
        words = parse_words(msg.get("words"), offset=start)
    return words


def _join(*texts: str) -> str:
    return " ".join(t.strip() for t in texts if t and t.strip())


class UtteranceState:
    """Stitching for one upstream session. Needs no socket, so fixture tests
    drive process() directly with documented wire frames."""

    def __init__(self, include_raw: bool = False):
        self.include_raw = include_raw
        self.error_message: str | None = None
        self.done = False
        self.final_end = 0.0  # end of the last final emitted
        self._reset()

    def _reset(self) -> None:
        self.utt_start: float | None = None
        self.locked_text = ""
        self.locked_words: list[Word] = []
        self.locked_end = 0.0

    def _merge(self, text: str, words: list[Word], start: float) -> tuple[str, list[Word]]:
        """The event's view of the whole utterance so far."""
        if not self.locked_text or (
            self.utt_start is not None and start <= self.utt_start + _EPS
        ):
            return text, words  # cumulative: already covers the locked text
        return _join(self.locked_text, text), self.locked_words + words

    def process(self, msg: dict) -> list[STTEvent]:
        kind = msg.get("type")
        raw = msg if self.include_raw else None

        if kind == "transcript.partial":
            start = float(msg.get("start") or 0.0)
            end = start + float(msg.get("duration") or 0.0)
            text = msg.get("text", "")
            words = _stream_words(msg, start)
            if self.utt_start is None:
                self.utt_start = start
            text, words = self._merge(text, words, start)
            if not text.strip() and self.locked_text:
                text, words = self.locked_text, self.locked_words
            utt_start = min(self.utt_start, words[0].start if words else start)
            end = max(end, self.locked_end)

            if msg.get("speech_final"):
                self._reset()
                events: list[STTEvent] = []
                if text.strip():
                    events.append(Transcript(
                        type="transcript", is_final=True, text=text,
                        words=words or None, start=utt_start, end=end, provider_raw=raw,
                    ))
                    self.final_end = end
                events.append(UtteranceEnd(type="utterance_end", at=end))
                return events

            if msg.get("is_final"):  # chunk final: locked, but the utterance goes on
                self.locked_text, self.locked_words, self.locked_end = text, words, end
            if not text.strip():
                return []
            return [Transcript(
                type="transcript", is_final=False, text=text,
                words=words or None, start=utt_start, end=end, provider_raw=raw,
            )]

        if kind == "transcript.done":
            self.done = True
            return self._flush(msg, raw)

        if kind == "error":
            self.error_message = str(msg.get("message") or "unknown error")
            return []

        # transcript.created (handled in connect) and anything additive.
        return []

    def _flush(self, msg: dict, raw) -> list[STTEvent]:
        """transcript.done: surface only what no final has carried yet."""
        text, words = self.locked_text, list(self.locked_words)
        start, locked_end = self.utt_start, self.locked_end
        tail = [w for w in parse_words(msg.get("words")) if w.start >= self.final_end - _EPS]
        tail = [w for w in tail if not words or w.start >= words[-1].end - _EPS]
        if tail:
            text, words = _join(text, *(w.w for w in tail)), words + tail
        elif not text and self.final_end == 0.0:
            text = msg.get("text", "")  # nothing emitted yet: the whole session
        self._reset()
        if not text.strip():
            return []
        end = words[-1].end if words else (locked_end or float(msg.get("duration") or 0.0))
        if start is None:
            start = words[0].start if words else 0.0
        self.final_end = end
        return [Transcript(
            type="transcript", is_final=True, text=text, words=words or None,
            start=start, end=end, provider_raw=raw,
        )]


def parse_message(raw: str, state: UtteranceState) -> list[STTEvent]:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(msg, dict):
        return []
    return state.process(msg)


@register_stt_stream("xai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "XAISTTStream":
    if not settings.xai_api_key:
        raise ProviderNotConfigured("xai")
    return XAISTTStream(settings.xai_api_key)


class XAISTTStream(STTStreamProvider):
    name = "xai"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, *, ws_url: str = WS_URL):
        self._api_key = api_key
        self._ws_url = ws_url
        self._ws: websockets.ClientConnection | None = None
        self._state = UtteranceState()
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        url = build_url(config, self._ws_url)  # validates audio params
        self._state = UtteranceState(include_raw=config.include_raw)
        try:
            self._ws = await ws_connect(
                url, additional_headers={"Authorization": f"Bearer {self._api_key}"}
            )
        except websockets.exceptions.InvalidStatus as exc:
            status = exc.response.status_code
            raise ProviderStreamError(
                f"xai connect rejected ({status})",
                # a bad key is 400 live (401 per the docs); 429/5xx retry
                recoverable=status not in (400, 401, 403),
                provider=self.name,
                code=str(status),
            ) from exc
        except Exception as exc:
            raise ProviderStreamError(
                f"xai connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        await self._await_ready()
        logger.info("xai connected", extra={"provider": self.name, "model": config.model})

    async def _await_ready(self) -> None:
        assert self._ws is not None
        try:
            while True:
                raw = await asyncio.wait_for(self._ws.recv(), READY_TIMEOUT)
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "transcript.created":
                    return
                if msg.get("type") == "error":
                    self._state.error_message = str(msg.get("message") or "unknown error")
        except websockets.exceptions.ConnectionClosed as exc:
            await self.close()
            raise self._closed_error(exc.code, exc.reason, "connect") from exc
        except TimeoutError as exc:
            await self.close()
            raise ProviderStreamError(
                "xai transcript.created timed out", recoverable=True, provider=self.name,
                code="timeout",
            ) from exc
        except Exception as exc:
            await self.close()
            raise ProviderStreamError(
                f"xai ready wait failed: {exc}", recoverable=True, provider=self.name
            ) from exc

    def _closed_error(self, code: int, reason: str, phase: str) -> ProviderStreamError:
        detail = self._state.error_message or reason or ""
        return ProviderStreamError(
            f"xai {phase} closed {code}: {detail}".rstrip(": "),
            recoverable=True,  # close codes are undocumented; let failover decide
            provider=self.name,
            code=str(code),
        )

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError("send before connect", recoverable=False, provider=self.name)
        try:
            await self._ws.send(chunk)
        except websockets.exceptions.ConnectionClosed as exc:
            raise self._closed_error(exc.code, exc.reason, "session") from exc

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                for event in parse_message(raw, self._state):
                    yield event
        except websockets.exceptions.ConnectionClosed as exc:
            if self._state.done or (self._finished and not self._state.error_message):
                return
            raise self._closed_error(exc.code, exc.reason, "session") from exc
        if not self._state.done and not self._finished:
            raise ProviderStreamError(
                f"xai session ended early: {self._state.error_message or 'closed'}",
                recoverable=True, provider=self.name,
            )

    async def finish(self) -> None:
        """audio.done: the server flushes, sends transcript.done and closes."""
        if self._finished or self._ws is None:
            return
        self._finished = True
        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            await self._ws.send(json.dumps({"type": "audio.done"}))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
