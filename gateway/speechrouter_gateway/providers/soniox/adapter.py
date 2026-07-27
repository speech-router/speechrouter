"""Soniox streaming STT adapter (raw WebSocket).

Protocol facts (docs/providers/soniox.md, verified 2026-07-27):
- No auth on handshake; first TEXT frame is the JSON config with api_key.
- Model stt-rt-v5. Tokens are SUBWORDS with embedded spacing — concatenate
  raw, never join with spaces; word boundaries appear as leading whitespace.
- Finals arrive exactly once (append); non-finals are wholesale-replaced by
  each message. Marker tokens <end> (endpoint) and <fin> (finalize ack) come
  INSIDE tokens[] and must be stripped from text but used as flush signals.
- End of audio = an EMPTY frame; server flushes, sends finished:true, closes.
- keepalive JSON required at least every 20s of send-silence.
- Errors arrive as a JSON frame with error_code/error_type, then the socket
  closes; branch on error_type (docs), not the message text.
- Billing is wall-clock stream duration -> capabilities.billing_basis makes
  the session layer close idle upstreams aggressively.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import Transcript, UtteranceEnd, Word
from ..base import (
    BillingBasis,
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream

WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
KEEPALIVE_INTERVAL = 10.0  # brief: required at least every 20s

_MARKERS = {"<end>", "<fin>"}

# error_types where reconnect/failover can help vs. ones where it cannot
_UNRECOVERABLE = {
    "invalid_request",
    "model_not_available",
    "unauthenticated",
    "organization_balance_exhausted",
    "organization_monthly_budget_exhausted",
    "project_monthly_budget_exhausted",
}

_ENCODING_MAP = {
    "linear16": "pcm_s16le",
    "linear32": "pcm_s32le",
    "mulaw": "mulaw",
    "alaw": "alaw",
}

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,
    endpointing=True,
    keyterms=True,
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
    realtime_pacing_required=True,  # bursts beyond realtime -> 408 "Input too slow"
    billing_basis=BillingBasis.SESSION_TIME,
)


def build_config_message(api_key: str, config: STTConfig) -> dict:
    message: dict = {
        "api_key": api_key,
        "model": config.model,
        "audio_format": _ENCODING_MAP[config.encoding],
        "sample_rate": config.sample_rate,
        "num_channels": config.channels,
        "enable_endpoint_detection": True,
    }
    if config.language:
        message["language_hints"] = [config.language]
        message["language_hints_strict"] = True
    if config.diarization:
        message["enable_speaker_diarization"] = True
    if config.keyterms:
        message["context"] = {"terms": list(config.keyterms)}
    message.update(config.provider_params)
    return message


@dataclass
class _TokenState:
    """Pure token algebra: finals append (with monotonic dedup), non-finals
    replace; markers trigger flushes. Fixture-testable without a socket."""

    pending_finals: list[dict] = field(default_factory=list)
    non_finals: list[dict] = field(default_factory=list)
    max_final_end_ms: float = 0.0

    def process(self, payload: dict) -> list[STTEvent]:
        if payload.get("error_message") or payload.get("error_type"):
            error_type = payload.get("error_type", "unknown")
            raise ProviderStreamError(
                f"soniox {error_type}: {payload.get('error_message', '')}",
                recoverable=error_type not in _UNRECOVERABLE,
                provider="soniox",
                code=error_type,
            )

        tokens = payload.get("tokens", [])
        events: list[STTEvent] = []
        if not tokens and not payload.get("finished"):
            return events

        saw_end = any(t.get("text", "").strip() == "<end>" for t in tokens)
        saw_fin = any(t.get("text", "").strip() == "<fin>" for t in tokens)

        fresh_non_finals: list[dict] = []
        for token in tokens:
            if token.get("text", "").strip() in _MARKERS:
                continue
            if token.get("is_final"):
                start_ms = token.get("start_ms")
                # Skip late official finals overlapping already-finalized audio
                if start_ms is not None and 0 < self.max_final_end_ms and (
                    start_ms < self.max_final_end_ms
                ):
                    continue
                self.pending_finals.append(token)
                end_ms = token.get("end_ms")
                if end_ms is not None and end_ms > self.max_final_end_ms:
                    self.max_final_end_ms = end_ms
            else:
                fresh_non_finals.append(token)
        self.non_finals = fresh_non_finals

        # Flush pending finals as one final transcript when the utterance
        # ended (<end>), a manual finalize was acked (<fin>), the stream
        # finished, or nothing provisional remains.
        should_flush = saw_end or saw_fin or payload.get("finished") or not self.non_finals
        if should_flush and self.pending_finals:
            events.append(self._transcript(self.pending_finals, is_final=True))
            self.pending_finals = []
        if saw_end:
            events.append(
                UtteranceEnd(type="utterance_end", at=round(self.max_final_end_ms / 1000.0, 3))
            )

        # Interim hypothesis: unflushed finals + current provisional tail.
        hypothesis = self.pending_finals + self.non_finals
        if hypothesis:
            events.append(self._transcript(hypothesis, is_final=False))
        return events

    def _transcript(self, tokens: list[dict], *, is_final: bool) -> Transcript:
        text = "".join(t.get("text", "") for t in tokens).strip()
        words = _tokens_to_words(tokens)
        timed = [t for t in tokens if t.get("start_ms") is not None]
        start = round(timed[0]["start_ms"] / 1000.0, 3) if timed else None
        end = round(max(t["end_ms"] for t in timed) / 1000.0, 3) if timed else None
        languages = {t["language"] for t in tokens if t.get("language")}
        return Transcript(
            type="transcript",
            is_final=is_final,
            text=text,
            words=words or None,
            start=start,
            end=end,
            lang=next(iter(languages)) if len(languages) == 1 else None,
        )


def _tokens_to_words(tokens: list[dict]) -> list[Word]:
    """Merge subword tokens into words: a token starting with whitespace (or
    following one that ended a word) starts a new word."""
    words: list[Word] = []
    current: list[dict] = []

    def push():
        if not current:
            return
        text = "".join(t.get("text", "") for t in current).strip()
        timed = [t for t in current if t.get("start_ms") is not None]
        if not text or not timed:
            current.clear()
            return
        confidences = [t["confidence"] for t in current if t.get("confidence") is not None]
        speaker = current[0].get("speaker")
        words.append(
            Word(
                w=text,
                start=round(timed[0]["start_ms"] / 1000.0, 3),
                end=round(max(t["end_ms"] for t in timed) / 1000.0, 3),
                conf=round(min(confidences), 4) if confidences else None,
                speaker=int(speaker) if speaker is not None and str(speaker).isdigit() else None,
                lang=current[0].get("language"),
            )
        )
        current.clear()

    for token in tokens:
        if token.get("text", "").startswith((" ", "\n", "\t")) and current:
            push()
        current.append(token)
    push()
    return words


@register_stt_stream("soniox", capabilities=CAPABILITIES)
def build(settings: Settings) -> "SonioxSTTStream":
    if not settings.soniox_api_key:
        raise ProviderNotConfigured("soniox")
    return SonioxSTTStream(settings.soniox_api_key)


class SonioxSTTStream(STTStreamProvider):
    name = "soniox"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_url: str = WS_URL):
        self._api_key = api_key
        self._ws_url = ws_url
        self._ws: websockets.ClientConnection | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._last_send = 0.0
        self._finished = False
        self._closed = False
        self._state = _TokenState()

    async def connect(self, config: STTConfig) -> None:
        try:
            self._ws = await websockets.connect(
                self._ws_url,
                ping_interval=None,  # Soniox liveness is its own keepalive JSON
            )
            await self._ws.send(json.dumps(build_config_message(self._api_key, config)))
        except Exception as exc:
            raise ProviderStreamError(
                f"soniox connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        self._last_send = asyncio.get_running_loop().time()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info("soniox connected", extra={"provider": self.name, "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        await self._ws.send(chunk)
        self._last_send = asyncio.get_running_loop().time()

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                for event in self._state.process(payload):
                    yield event
                if payload.get("finished"):
                    return
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"soniox closed {exc.code}: {exc.reason}",
                recoverable=True,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send("")  # empty frame = end of audio (per docs)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._ws is None or self._finished:
                    return
                idle = asyncio.get_running_loop().time() - self._last_send
                if idle >= KEEPALIVE_INTERVAL:
                    try:
                        await self._ws.send(json.dumps({"type": "keepalive"}))
                    except websockets.exceptions.ConnectionClosed:
                        return
        except asyncio.CancelledError:
            pass
