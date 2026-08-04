"""Telnyx streaming STT adapter (raw WebSocket, /v2/speech-to-text/transcription).

Protocol facts (docs/providers/telnyx.md, verified 2026-08-04):
- Auth: `Authorization: Bearer <key>` header on the WS upgrade.
- All config is URL query params; there is NO config frame after connect.
  Sending a JSON config frame is ignored and produces no response.
- Up: raw PCM as binary WebSocket frames (16-bit little-endian, mono).
- Down: one JSON text frame per finalized transcript:
    {"transcript": " ...", "confidence": null, "is_final": true}
  No interim frames, no word timestamps, no diarization, no endpointing
  signals, no speech_started. The engine emits a single final transcript
  after audio stops arriving, then closes the socket (1000 OK).
- `transcription_engine` selects the upstream model; only `Telnyx` is
  exposed here (Deepgram/Google/Azure have their own first-class adapters).
- `interim_results=true` in the URL suppresses ALL output from the Telnyx
  engine (verified) -> Capabilities.interim_results is False so the
  resolver never asks for them.
- No CloseStream: that frame is documented for Deepgram/Speechmatics/Soniox
  engines only. finish() is a no-op; the server flushes and closes on its
  own once audio stops.
- Billing: per minute of audio processed (AUDIO_TIME).
"""

from collections.abc import AsyncIterator

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import Transcript
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream
from ..wsconnect import ws_connect

WS_BASE = "wss://api.telnyx.com/v2/speech-to-text/transcription"

_ENCODING_MAP = {
    "linear16": "linear16",
    "mulaw": "mulaw",
    "alaw": "alaw",
}

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=False,  # Telnyx engine only emits a single final
    word_timestamps=False,
    diarization=False,
    endpointing=False,
    keyterms=False,
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
)


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    """Build the WebSocket URL with query params. Model is the engine name."""
    params: list[tuple[str, str]] = [
        ("transcription_engine", config.model.capitalize()),
        ("input_format", _ENCODING_MAP[config.encoding]),
        ("sample_rate", str(config.sample_rate)),
    ]
    if config.language and config.language != "auto":
        params.append(("language", config.language))
    for key, value in config.provider_params.items():
        params.append((key, str(value)))
    from urllib.parse import urlencode
    return f"{base}?{urlencode(params)}"


def parse_message(raw: str, include_raw: bool = False) -> list[STTEvent]:
    """Pure translation of one Telnyx JSON frame into normalized events.

    Side-effect free so fixture tests can drive it without a socket.
    """
    import json
    msg = json.loads(raw)
    events: list[STTEvent] = []

    # Telnyx error frames: {"errors": [...]} -- not transcript data.
    if msg.get("errors"):
        return events

    text = msg.get("transcript", "")
    if not text.strip():
        return events

    events.append(
        Transcript(
            type="transcript",
            is_final=bool(msg.get("is_final", True)),
            text=text,
            words=None,  # no word timestamps from Telnyx engine
            start=None,
            end=None,
            lang=None,
            provider_raw=msg if include_raw else None,
        )
    )
    return events


@register_stt_stream("telnyx", capabilities=CAPABILITIES)
def build(settings: Settings) -> "TelnyxSTTStream":
    if not settings.telnyx_api_key:
        raise ProviderNotConfigured("telnyx")
    return TelnyxSTTStream(settings.telnyx_api_key)


class TelnyxSTTStream(STTStreamProvider):
    name = "telnyx"
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
        url = build_url(config, self._ws_base)
        try:
            self._ws = await ws_connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                ping_interval=None,  # short-lived stream; no app-level keepalive
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"telnyx connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("telnyx connected", extra={"provider": self.name, "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError("send before connect", recoverable=False, provider=self.name)
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
                for event in parse_message(raw, self._include_raw):
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"telnyx closed {exc.code}: {exc.reason}",
                recoverable=exc.code != 1011,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        # No explicit flush signal for the Telnyx engine. The server emits the
        # final transcript after audio stops and closes the socket. Mark
        # finished so events() tolerates the close.
        self._finished = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
