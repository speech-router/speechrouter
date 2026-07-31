"""OpenAI Realtime transcription adapter.

Protocol facts (docs/providers/openai.md, verified 2026-07-27):
- WS wss://api.openai.com/v1/realtime?intent=transcription, Bearer auth.
- GA session shape is NESTED: session.audio.input.{format, transcription}.
- Audio travels as BASE64 inside input_audio_buffer.append JSON events (the
  one provider where binary frames don't exist).
- Deltas are text FRAGMENTS per item — we accumulate per item_id and emit
  the growing hypothesis as interims; `completed` carries the full item
  transcript as the final.
- No word timestamps and no diarization in realtime: finals carry no
  start/end, so the session's failover dedup cannot key on time for this
  provider (documented capability gap; failover replay may repeat text).
- gpt-realtime-whisper streams natively (omit turn_detection); gpt-4o-*
  models need server_vad. VAD events map to speech_started/utterance_end.
"""

import array
import asyncio
import base64
import json
from collections.abc import AsyncIterator

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import SpeechStarted, Transcript, UtteranceEnd
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream
from ..wsconnect import ws_connect

WS_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
DRAIN_TIMEOUT = 5.0

_FORMAT_MAP = {"linear16": "audio/pcm", "mulaw": "audio/pcmu", "alaw": "audio/pcma"}
OPENAI_RATE = 24000  # GA realtime rejects pcm below 24 kHz (live, 2026-07-31)
_NATIVE_STREAMING_MODELS = {"gpt-realtime-whisper"}

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=False,
    diarization=False,
    endpointing=True,
    languages=frozenset({"auto"}),
    encodings=frozenset(_FORMAT_MAP),
    sample_rates=frozenset({24000}),  # documented rate for audio/pcm
)


def build_session_update(config: STTConfig) -> dict:
    transcription: dict = {"model": config.model}
    if config.language:
        transcription["language"] = config.language
    # GA realtime requires >= 24 kHz pcm; the adapter upsamples client
    # audio to OPENAI_RATE so any inbound rate keeps working.
    rate = OPENAI_RATE if config.encoding == "linear16" else config.sample_rate
    audio_input: dict = {
        "format": {"type": _FORMAT_MAP[config.encoding], "rate": rate},
        "transcription": transcription,
    }
    # turn_detection moved under audio.input in the GA realtime schema
    # (session-level placement rejected live 2026-07-31: unknown_parameter)
    if config.model not in _NATIVE_STREAMING_MODELS:
        audio_input["turn_detection"] = {"type": "server_vad"}
    session: dict = {"type": "transcription", "audio": {"input": audio_input}}
    for key, value in config.provider_params.items():
        session[key] = value
    return {"type": "session.update", "session": session}


def parse_event(
    msg: dict, accumulator: dict[str, str], include_raw: bool = False
) -> list[STTEvent]:
    """Pure translation; accumulator maps item_id -> accumulated delta text."""
    msg_type = msg.get("type", "")
    events: list[STTEvent] = []
    if msg_type == "conversation.item.input_audio_transcription.delta":
        item_id = msg.get("item_id", "")
        accumulator[item_id] = accumulator.get(item_id, "") + msg.get("delta", "")
        if accumulator[item_id].strip():
            events.append(
                Transcript(type="transcript", is_final=False, text=accumulator[item_id],
                           provider_raw=msg if include_raw else None)
            )
    elif msg_type == "conversation.item.input_audio_transcription.completed":
        item_id = msg.get("item_id", "")
        accumulator.pop(item_id, None)
        text = msg.get("transcript", "")
        if text.strip():
            events.append(Transcript(type="transcript", is_final=True, text=text,
                                     provider_raw=msg if include_raw else None))
    elif msg_type == "input_audio_buffer.speech_started":
        events.append(
            SpeechStarted(
                type="speech_started", at=float(msg.get("audio_start_ms", 0)) / 1000.0
            )
        )
    elif msg_type == "input_audio_buffer.speech_stopped":
        events.append(
            UtteranceEnd(type="utterance_end", at=float(msg.get("audio_end_ms", 0)) / 1000.0)
        )
    elif msg_type == "error":
        error = msg.get("error", {})
        code = str(error.get("code") or error.get("type") or "")
        raise ProviderStreamError(
            f"openai realtime error {code}: {error.get('message', '')}",
            recoverable="auth" not in code and "invalid" not in code,
            provider="openai",
            code=code,
        )
    return events


@register_stt_stream("openai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "OpenAIRealtimeSTT":
    if not settings.openai_api_key:
        raise ProviderNotConfigured("openai")
    return OpenAIRealtimeSTT(settings.openai_api_key)


class OpenAIRealtimeSTT(STTStreamProvider):
    name = "openai"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_url: str = WS_URL):
        self._api_key = api_key
        self._ws_url = ws_url
        self._ws: websockets.ClientConnection | None = None
        self._accumulator: dict[str, str] = {}
        self._finished = False
        self._closed = False
        self._include_raw = False
        self._step = 1.0  # input samples advanced per output sample
        self._pos = 0.0
        self._prev: int | None = None

    async def connect(self, config: STTConfig) -> None:
        self._include_raw = config.include_raw
        if config.encoding == "linear16" and config.sample_rate != OPENAI_RATE:
            self._step = config.sample_rate / OPENAI_RATE
        try:
            self._ws = await ws_connect(
                self._ws_url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
            )
            await self._ws.send(json.dumps(build_session_update(config)))
        except Exception as exc:
            raise ProviderStreamError(
                f"openai realtime connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("openai realtime connected", extra={"provider": self.name,
                                                        "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        if self._step != 1.0:
            chunk = self._upsample(chunk)
        await self._ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode(),
                }
            )
        )

    def _upsample(self, chunk: bytes) -> bytes:
        """Linear-interpolate int16 PCM up to OPENAI_RATE with cross-chunk
        phase continuity (16 kHz -> 24 kHz is the common 2/3-step case)."""
        src = array.array("h")
        src.frombytes(chunk)
        if self._prev is not None:
            src.insert(0, self._prev)
        out = array.array("h")
        pos = self._pos
        limit = len(src) - 1
        while pos < limit:
            i = int(pos)
            frac = pos - i
            out.append(int(src[i] * (1 - frac) + src[i + 1] * frac))
            pos += self._step
        self._pos = pos - limit
        self._prev = src[-1] if len(src) else self._prev
        return out.tobytes()

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            while True:
                if self._finished:
                    # No explicit end-of-stream event exists; drain with a
                    # grace timeout after the client finalizes.
                    try:
                        raw = await asyncio.wait_for(self._ws.recv(), timeout=DRAIN_TIMEOUT)
                    except TimeoutError:
                        return
                else:
                    raw = await self._ws.recv()
                if isinstance(raw, bytes):
                    continue
                for event in parse_event(json.loads(raw), self._accumulator,
                                         self._include_raw):
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"openai realtime closed {exc.code}: {exc.reason}",
                recoverable=exc.code != 1008,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
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
