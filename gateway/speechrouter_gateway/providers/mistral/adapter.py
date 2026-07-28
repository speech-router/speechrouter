"""Mistral (Voxtral) realtime transcription adapter.

Wire protocol verified from the official SDK source (docs/providers/mistral.md,
commit b0613c7, 2026-07-27):
- Server speaks FIRST: connect() waits for session.created (readiness
  contract), then sends session.update when a latency target is requested.
- Audio is base64 in input_audio.append JSON text frames, max 262144 decoded
  bytes per message — send_audio splits larger chunks.
- Shutdown: input_audio.flush -> input_audio.end -> read until
  transcription.done.
- transcription.text.delta carries incremental text (accumulated into the
  interim hypothesis); transcription.segment is a finalized span with
  start/end seconds; transcription.done carries the full text (only emitted
  as a final here if no segments were ever delivered).
- No app-level keepalive: standard WS ping/pong (websockets defaults).
"""

import asyncio
import base64
import json
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

WS_BASE = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
MAX_DECODED_BYTES = 262144

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
    word_timestamps=False,  # segment-level times only
    diarization=False,
    endpointing=True,  # segments are server-finalized spans
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
)


class _StreamState:
    """Pure event translation; fixture-testable."""

    def __init__(self, include_raw: bool = False) -> None:
        self.include_raw = include_raw
        self.hypothesis = ""
        self.language: str | None = None
        self.segments_emitted = 0
        self.done = False

    def process(self, msg: dict) -> list[STTEvent]:
        msg_type = msg.get("type", "")
        events: list[STTEvent] = []
        if msg_type == "transcription.text.delta":
            self.hypothesis += msg.get("text", "")
            if self.hypothesis.strip():
                events.append(
                    Transcript(
                        type="transcript", is_final=False, text=self.hypothesis,
                        lang=self.language,
                        provider_raw=msg if self.include_raw else None,
                    )
                )
        elif msg_type == "transcription.segment":
            text = msg.get("text", "")
            self.hypothesis = ""
            if text.strip():
                self.segments_emitted += 1
                events.append(
                    Transcript(
                        type="transcript",
                        is_final=True,
                        text=text,
                        start=msg.get("start"),
                        end=msg.get("end"),
                        lang=self.language,
                        provider_raw=msg if self.include_raw else None,
                    )
                )
        elif msg_type == "transcription.language":
            self.language = msg.get("audio_language")
        elif msg_type == "transcription.done":
            self.done = True
            text = msg.get("text", "")
            if self.segments_emitted == 0 and text.strip():
                events.append(
                    Transcript(
                        type="transcript", is_final=True, text=text,
                        lang=msg.get("language") or self.language,
                        provider_raw=msg if self.include_raw else None,
                    )
                )
        elif msg_type == "error":
            error = msg.get("error", {})
            message = error.get("message")
            code = error.get("code")
            raise ProviderStreamError(
                f"mistral realtime error {code}: {json.dumps(message)[:200]}",
                recoverable=not isinstance(code, int) or code >= 500 or code == 429,
                provider="mistral",
                code=str(code),
            )
        return events


def build_session_update(config: STTConfig) -> dict | None:
    session: dict = {}
    encoding = _ENCODING_MAP[config.encoding]
    session["audio_format"] = {"encoding": encoding, "sample_rate": config.sample_rate}
    delay = config.provider_params.get("target_streaming_delay_ms")
    if delay is not None:
        session["target_streaming_delay_ms"] = int(delay)
    return {"type": "session.update", "session": session}


@register_stt_stream("mistral", capabilities=CAPABILITIES)
def build(settings: Settings) -> "MistralRealtimeSTT":
    if not settings.mistral_api_key:
        raise ProviderNotConfigured("mistral")
    return MistralRealtimeSTT(settings.mistral_api_key)


class MistralRealtimeSTT(STTStreamProvider):
    name = "mistral"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._state = _StreamState()
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        self._state = _StreamState(include_raw=config.include_raw)
        url = f"{self._ws_base}?model={config.model}"
        try:
            self._ws = await ws_connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
            )
            # Server speaks first: wait for session.created before audio.
            while True:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=15.0)
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "session.created":
                    break
                self._state.process(msg)  # surfaces early error events
            update = build_session_update(config)
            if update is not None:
                await self._ws.send(json.dumps(update))
        except ProviderStreamError:
            raise
        except Exception as exc:
            raise ProviderStreamError(
                f"mistral realtime connect failed: {exc}", recoverable=True,
                provider=self.name,
            ) from exc
        logger.info("mistral realtime connected", extra={"provider": self.name,
                                                         "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        for i in range(0, len(chunk), MAX_DECODED_BYTES):
            await self._ws.send(
                json.dumps(
                    {
                        "type": "input_audio.append",
                        "audio": base64.b64encode(chunk[i : i + MAX_DECODED_BYTES]).decode(),
                    }
                )
            )

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                for event in self._state.process(json.loads(raw)):
                    yield event
                if self._state.done:
                    return
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"mistral realtime closed {exc.code}: {exc.reason}",
                recoverable=exc.code != 1008,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(json.dumps({"type": "input_audio.flush"}))
            await self._ws.send(json.dumps({"type": "input_audio.end"}))
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
