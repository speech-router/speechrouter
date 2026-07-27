"""Cartesia STT adapter (classic WS endpoint, both ink models).

Protocol facts (docs/providers/cartesia.md, verified 2026-07-27):
- wss://api.cartesia.ai/stt/websocket with required cartesia_version pin.
- Control commands are PLAIN TEXT STRINGS ("finalize", "close") — not JSON.
- transcript.text on finals is a DELTA since the last finalized chunk;
  concatenate verbatim, never touch whitespace. Words carry start/end secs.
- flush_done acks finalize; done acks close, then the socket closes.
- The turns endpoint (ink-2 server-driven turn lifecycle) is a separate,
  later adapter — classic gives us manual finalize which fits the gateway.
"""

import json
import urllib.parse
from collections.abc import AsyncIterator

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import Transcript, Word
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream

WS_BASE = "wss://api.cartesia.ai/stt/websocket"
CARTESIA_VERSION = "2026-03-01"

_ENCODING_MAP = {
    "linear16": "pcm_s16le",
    "linear32": "pcm_s32le",
    "mulaw": "pcm_mulaw",
    "alaw": "pcm_alaw",
}

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=True,
    diarization=False,
    endpointing=False,  # classic endpoint: manual finalize, no VAD events
    keyterms=True,
    keyterms_max=100,
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
)


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    params: list[tuple[str, str]] = [
        ("model", config.model),
        ("encoding", _ENCODING_MAP[config.encoding]),
        ("sample_rate", str(config.sample_rate)),
        ("cartesia_version", CARTESIA_VERSION),
    ]
    if config.language:
        params.append(("language", config.language))
    if config.keyterms and config.model.startswith("ink-2"):
        params.extend(("keyterm", t) for t in config.keyterms)
    for key, value in config.provider_params.items():
        params.append((key, str(value)))
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_message(raw: str) -> tuple[str, list[STTEvent]]:
    """Returns (kind, events): kind in {"events", "flush_done", "done"}."""
    msg = json.loads(raw)
    msg_type = msg.get("type")
    if msg_type == "transcript":
        text = msg.get("text", "")
        if not text.strip():
            return "events", []
        words = [
            Word(w=w["word"], start=float(w["start"]), end=float(w["end"]))
            for w in msg.get("words") or []
            if w.get("start") is not None
        ]
        return "events", [
            Transcript(
                type="transcript",
                is_final=bool(msg.get("is_final")),
                text=text,
                words=words or None,
                start=words[0].start if words else None,
                end=words[-1].end if words else None,
                lang=msg.get("language"),
            )
        ]
    if msg_type == "flush_done":
        return "flush_done", []
    if msg_type == "done":
        return "done", []
    if msg_type == "error":
        status = int(msg.get("status_code") or 500)
        raise ProviderStreamError(
            f"cartesia {msg.get('error_code', '')}: {msg.get('message', '')}",
            recoverable=status >= 500,
            provider="cartesia",
            code=str(msg.get("error_code", "")),
        )
    return "events", []


@register_stt_stream("cartesia", capabilities=CAPABILITIES)
def build(settings: Settings) -> "CartesiaSTTStream":
    if not settings.cartesia_api_key:
        raise ProviderNotConfigured("cartesia")
    return CartesiaSTTStream(settings.cartesia_api_key)


class CartesiaSTTStream(STTStreamProvider):
    name = "cartesia"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        try:
            self._ws = await websockets.connect(
                build_url(config, self._ws_base),
                additional_headers={"X-API-Key": self._api_key},
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"cartesia connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("cartesia connected", extra={"provider": self.name, "model": config.model})

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
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                kind, parsed = parse_message(raw)
                if kind == "done":
                    return
                for event in parsed:
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"cartesia closed {exc.code}: {exc.reason}",
                recoverable=exc.code != 1008,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send("finalize")  # plain string command per docs
            await self._ws.send("close")
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
