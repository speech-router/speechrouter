"""Cartesia Turns adapter (ink-2 server-driven turn lifecycle).

Protocol facts (docs/providers/cartesia.md): wss://api.cartesia.ai/stt/turns/
websocket; server events connected / turn.start / turn.update /
turn.eager_end / turn.resume / turn.end; transcript is CUMULATIVE within a
turn; all emitted text is final (no revisions); NO word timestamps and no
event timestamps on this endpoint.

Because the wire carries no time base, this adapter keeps its own audio
clock (seconds of audio sent) and stamps speech_started/utterance_end with
it — monotonic and close to real, though slightly ahead during buffering.
turn.eager_end / turn.resume are DROPPED (no eager semantics in our
protocol yet; additive later). Slug model "ink-2-turns" maps to provider
model "ink-2" via the dispatch layer.
"""

import json
import urllib.parse
from collections.abc import AsyncIterator

import websockets

from ...logging import logger
from ...protocol import SpeechStarted, Transcript, UtteranceEnd
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..wsconnect import ws_connect
from .adapter import _ENCODING_MAP, CARTESIA_VERSION

WS_BASE = "wss://api.cartesia.ai/stt/turns/websocket"

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=True,
    word_timestamps=False,
    diarization=False,
    endpointing=True,
    keyterms=True,
    keyterms_max=100,
    languages=frozenset({"en"}),
    encodings=frozenset(_ENCODING_MAP),
    turn_based=True,
)


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    params: list[tuple[str, str]] = [
        ("model", config.model),
        ("encoding", _ENCODING_MAP[config.encoding]),
        ("sample_rate", str(config.sample_rate)),
        ("cartesia_version", CARTESIA_VERSION),
    ]
    if config.keyterms:
        params.extend(("keyterm", t) for t in config.keyterms)
    for key, value in config.provider_params.items():
        params.append((key, str(value)))  # turn_start_threshold, ... turn_end_timeout_ms
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_message(raw: str, audio_clock: float) -> list[STTEvent]:
    """audio_clock = seconds of audio the adapter has sent so far."""
    msg = json.loads(raw)
    msg_type = msg.get("type")
    if msg_type == "error":
        status = int(msg.get("status_code") or 500)
        raise ProviderStreamError(
            f"cartesia turns {msg.get('error_code', '')}: {msg.get('message', '')}",
            recoverable=status >= 500,
            provider="cartesia",
            code=str(msg.get("error_code", "")),
        )
    if msg_type == "turn.start":
        return [SpeechStarted(type="speech_started", at=round(audio_clock, 3))]
    if msg_type == "turn.update":
        text = msg.get("transcript", "")
        return (
            [Transcript(type="transcript", is_final=False, text=text)] if text.strip() else []
        )
    if msg_type == "turn.end":
        text = msg.get("transcript", "")
        events: list[STTEvent] = []
        if text.strip():
            events.append(Transcript(type="transcript", is_final=True, text=text))
        events.append(UtteranceEnd(type="utterance_end", at=round(audio_clock, 3)))
        return events
    # connected / turn.eager_end / turn.resume: dropped in v1
    return []


class CartesiaTurnsStream(STTStreamProvider):
    name = "cartesia"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._byte_rate = 32000
        self._audio_clock = 0.0
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        if config.diarization:
            raise ProviderStreamError(
                "cartesia turns does not support diarization",
                recoverable=False, provider=self.name,
            )
        per_sample = {"linear16": 2, "linear32": 4, "mulaw": 1, "alaw": 1}[config.encoding]
        self._byte_rate = config.sample_rate * per_sample * config.channels
        try:
            self._ws = await ws_connect(
                build_url(config, self._ws_base),
                additional_headers={"X-API-Key": self._api_key},
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"cartesia turns connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("cartesia turns connected", extra={"provider": self.name,
                                                       "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        await self._ws.send(chunk)
        self._audio_clock += len(chunk) / self._byte_rate

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                for event in parse_message(raw, self._audio_clock):
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"cartesia turns closed {exc.code}: {exc.reason}",
                recoverable=exc.code != 1008,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(json.dumps({"type": "close"}))
        except websockets.exceptions.ConnectionClosed:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
