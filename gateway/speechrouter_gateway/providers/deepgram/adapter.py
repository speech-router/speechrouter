"""Deepgram streaming STT adapter (raw WebSocket, /v1/listen).

Protocol facts (docs/providers/deepgram.md, verified 2026-07-27):
- Auth header scheme is `Token`, not Bearer.
- Control JSON must go as TEXT frames; binary JSON is treated as audio.
- KeepAlive every 3-5s of send-silence or the server closes 1011/NET-0001 at ~10s.
- `is_final` freezes text for a range (can fire mid-utterance); `speech_final`
  is the endpointing signal. Concatenate is_final segments until speech_final.
- finish() sends {"type":"CloseStream"}; server flushes, sends final Results
  then Metadata, then closes — events() exhausts on that close.
- keyterm (nova-3/flux) vs keywords (nova-2 and older `word:boost`) — routed
  by model family here.
"""

import asyncio
import json
import urllib.parse
from collections.abc import AsyncIterator

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import SpeechStarted, Transcript, UtteranceEnd, Word
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..dispatch import ModelDispatchStream
from ..registry import ProviderNotConfigured, register_stt_stream
from ..wsconnect import ws_connect

WS_BASE = "wss://api.deepgram.com/v1/listen"
KEEPALIVE_INTERVAL = 5.0

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,
    endpointing=True,
    keyterms=True,
    languages=frozenset({"auto"}),  # per-model in models.json; multi on nova-3
    encodings=frozenset({"linear16", "linear32", "mulaw", "alaw", "opus", "ogg-opus", "flac"}),
)


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    params: list[tuple[str, str]] = [
        ("model", config.model),
        ("encoding", config.encoding),
        ("sample_rate", str(config.sample_rate)),
        ("channels", str(config.channels)),
        ("punctuate", "true"),
        ("interim_results", "true" if config.interim_results else "false"),
    ]
    if config.language:
        params.append(("language", config.language))
    if config.diarization:
        params.append(("diarize", "true"))
    if config.interim_results:
        # utterance_end_ms requires interim_results per docs
        params.append(("utterance_end_ms", "1000"))
        params.append(("vad_events", "true"))
    if config.keyterms:
        if config.model.startswith(("nova-3", "flux")):
            params.extend(("keyterm", term) for term in config.keyterms)
        else:
            params.extend(("keywords", f"{term}:2") for term in config.keyterms)
    for key, value in config.provider_params.items():
        params.append((key, str(value)))
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_message(raw: str, last_utterance_end: float) -> tuple[list[STTEvent], float]:
    """Pure translation of one Deepgram text frame into normalized events.

    Returns (events, updated last_utterance_end). Kept side-effect free so
    fixture tests can drive it without a socket.
    """
    msg = json.loads(raw)
    events: list[STTEvent] = []
    msg_type = msg.get("type")

    if msg_type == "Results":
        alternatives = msg.get("channel", {}).get("alternatives", [])
        alt = alternatives[0] if alternatives else {}
        text = alt.get("transcript", "")
        start = float(msg.get("start", 0.0))
        duration = float(msg.get("duration", 0.0))
        if text.strip():
            words = [
                Word(
                    w=w.get("punctuated_word") or w["word"],
                    start=float(w["start"]),
                    end=float(w["end"]),
                    conf=w.get("confidence"),
                    speaker=w.get("speaker"),
                    lang=w.get("language"),
                )
                for w in alt.get("words", [])
            ]
            languages = alt.get("languages") or []
            events.append(
                Transcript(
                    type="transcript",
                    is_final=bool(msg.get("is_final", False)),
                    text=text,
                    words=words or None,
                    start=start,
                    end=start + duration,
                    lang=languages[0] if languages else None,
                )
            )
        if msg.get("speech_final"):
            end_at = start + duration
            events.append(UtteranceEnd(type="utterance_end", at=end_at))
            last_utterance_end = end_at
    elif msg_type == "UtteranceEnd":
        # Fallback signal for gaps endpointing missed. last_word_end == -1 is
        # the documented "already finalized" sentinel; suppress duplicates for
        # utterances speech_final already closed.
        last_word_end = float(msg.get("last_word_end", -1.0))
        if last_word_end > last_utterance_end:
            events.append(UtteranceEnd(type="utterance_end", at=last_word_end))
            last_utterance_end = last_word_end
    elif msg_type == "SpeechStarted":
        events.append(SpeechStarted(type="speech_started", at=float(msg.get("timestamp", 0.0))))
    # Metadata / other message types carry no client-facing events.

    return events, last_utterance_end


@register_stt_stream("deepgram", capabilities=CAPABILITIES)
def build(settings: Settings) -> "ModelDispatchStream":
    if not settings.deepgram_api_key:
        raise ProviderNotConfigured("deepgram")
    api_key = settings.deepgram_api_key

    def choose(config: STTConfig) -> tuple[STTStreamProvider, STTConfig]:
        if config.model.startswith("flux"):
            from .flux import DeepgramFluxStream  # noqa: PLC0415 - avoid import cycle

            return DeepgramFluxStream(api_key), config
        return DeepgramSTTStream(api_key), config

    return ModelDispatchStream("deepgram", CAPABILITIES, choose)


class DeepgramSTTStream(STTStreamProvider):
    name = "deepgram"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._last_send = 0.0
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        url = build_url(config, self._ws_base)
        try:
            self._ws = await ws_connect(
                url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
                ping_interval=None,  # Deepgram liveness is KeepAlive-based
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"deepgram connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        self._last_send = asyncio.get_running_loop().time()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info("deepgram connected", extra={"provider": self.name, "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError("send before connect", recoverable=False, provider=self.name)
        await self._ws.send(chunk)
        self._last_send = asyncio.get_running_loop().time()

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        last_utterance_end = -1.0
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue  # Deepgram sends no meaningful binary frames
                parsed, last_utterance_end = parse_message(raw, last_utterance_end)
                for event in parsed:
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass  # normal end after CloseStream
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return  # server closed after flush; treat as clean end
            # 1011 covers NET-0000 (server-side, retry) and NET-0001 (our
            # silence); 1008/DATA-0000 means the audio config is wrong and a
            # retry with identical config cannot succeed.
            recoverable = exc.code != 1008
            raise ProviderStreamError(
                f"deepgram closed {exc.code}: {exc.reason}",
                recoverable=recoverable,
                provider=self.name,
                code=str(exc.code),
            ) from exc

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
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass

    async def _keepalive_loop(self) -> None:
        """Text-frame KeepAlive when no audio flowed for KEEPALIVE_INTERVAL."""
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._ws is None or self._finished:
                    return
                idle = asyncio.get_running_loop().time() - self._last_send
                if idle >= KEEPALIVE_INTERVAL:
                    try:
                        await self._ws.send(json.dumps({"type": "KeepAlive"}))
                    except websockets.exceptions.ConnectionClosed:
                        return
        except asyncio.CancelledError:
            pass
