"""Deepgram Flux adapter (v2 turn-based conversational protocol).

Protocol facts (docs/providers/deepgram.md): SEPARATE endpoint
wss://api.deepgram.com/v2/listen — not a model swap on v1. TurnInfo events
(Update | StartOfTurn | EagerEndOfTurn | TurnResumed | EndOfTurn) with
sequence_id ordering; 80ms chunks recommended; no interim_results/
endpointing/utterance_end params (turn logic replaces them); NO documented
KeepAlive (WS protocol pings keep liveness instead).

Mapping to our spec: Update -> interim transcript, StartOfTurn ->
speech_started, EndOfTurn -> final transcript + utterance_end.
EagerEndOfTurn/TurnResumed are DROPPED for now — our protocol has no eager
semantics yet; adding turn.eager_end/turn.resumed events later is additive
and non-breaking (noted in docs/providers/others.md).
"""

import json
import urllib.parse
from collections.abc import AsyncIterator

import websockets

from ...logging import logger
from ...protocol import SpeechStarted, Transcript, UtteranceEnd, Word
from ..base import (
    BillingBasis,
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..wsconnect import ws_connect

WS_BASE = "wss://api.deepgram.com/v2/listen"

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=True,
    word_timestamps=True,
    diarization=False,  # not offered on Flux
    endpointing=True,
    keyterms=True,
    languages=frozenset({"auto"}),
    encodings=frozenset({"linear16", "linear32", "mulaw", "alaw", "opus", "ogg-opus"}),
    chunk_ms_min=0,
    chunk_ms_max=0,
    billing_basis=BillingBasis.AUDIO_TIME,
    turn_based=True,
)


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    params: list[tuple[str, str]] = [
        ("model", config.model),
        ("encoding", config.encoding),
        ("sample_rate", str(config.sample_rate)),
    ]
    if config.language:
        params.append(("language_hint", config.language))
    if config.keyterms:
        params.extend(("keyterm", t) for t in config.keyterms)
    for key, value in config.provider_params.items():
        params.append((key, str(value)))  # eot_threshold, eager_eot_threshold, ...
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_message(raw: str, include_raw: bool = False) -> list[STTEvent]:
    msg = json.loads(raw)
    msg_type = msg.get("type")
    if msg_type == "Error":
        raise ProviderStreamError(
            f"deepgram flux error {msg.get('code', '')}: {msg.get('description', '')}",
            recoverable=True,
            provider="deepgram",
            code=str(msg.get("code", "")),
        )
    if msg_type != "TurnInfo":
        return []  # Connected / ConfigureSuccess etc.

    event = msg.get("event")
    window_start = float(msg.get("audio_window_start", 0.0))
    window_end = float(msg.get("audio_window_end", 0.0))
    if event == "StartOfTurn":
        return [SpeechStarted(type="speech_started", at=window_start)]
    if event in ("EagerEndOfTurn", "TurnResumed"):
        return []  # no eager semantics in our protocol yet (documented drop)
    if event not in ("Update", "EndOfTurn"):
        return []

    text = msg.get("transcript", "")
    if not text.strip():
        return []
    words = [
        Word(
            w=w.get("word", ""),
            start=float(w["start"]),
            end=float(w["end"]),
            conf=w.get("confidence"),
        )
        for w in msg.get("words", [])
        if w.get("start") is not None
    ]
    is_final = event == "EndOfTurn"
    events: list[STTEvent] = [
        Transcript(
            type="transcript",
            is_final=is_final,
            text=text,
            words=words or None,
            start=window_start,
            end=window_end,
            provider_raw=msg if include_raw else None,
        )
    ]
    if is_final:
        events.append(UtteranceEnd(type="utterance_end", at=window_end))
    return events


class DeepgramFluxStream(STTStreamProvider):
    name = "deepgram"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._finished = False
        self._closed = False
        self._include_raw = False

    async def connect(self, config: STTConfig) -> None:
        self._include_raw = config.include_raw
        if config.diarization:
            raise ProviderStreamError(
                "deepgram flux does not support diarization",
                recoverable=False, provider=self.name,
            )
        try:
            self._ws = await ws_connect(
                build_url(config, self._ws_base),
                additional_headers={"Authorization": f"Token {self._api_key}"},
                # No JSON KeepAlive on Flux: rely on WS protocol pings.
                ping_interval=20,
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"deepgram flux connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("deepgram flux connected", extra={"provider": self.name,
                                                      "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        await self._ws.send(chunk)

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        # Flux only emits EndOfTurn after trailing silence (eot_timeout_ms);
        # a stream that ends mid-turn would otherwise lose its last words.
        # Track the newest Update and promote it to a final on clean close.
        pending: Transcript | None = None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                for event in parse_message(raw, self._include_raw):
                    if isinstance(event, Transcript):
                        pending = None if event.is_final else event
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if not self._finished:
                raise ProviderStreamError(
                    f"deepgram flux closed {exc.code}: {exc.reason}",
                    recoverable=exc.code != 1008,
                    provider=self.name,
                    code=str(exc.code),
                ) from exc
        if pending is not None:
            yield pending.model_copy(update={"is_final": True})
            if pending.end is not None:
                yield UtteranceEnd(type="utterance_end", at=pending.end)

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(json.dumps({"type": "CloseStream"}))
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
