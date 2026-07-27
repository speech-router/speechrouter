"""AssemblyAI Universal-Streaming v3 adapter.

Protocol facts (docs/providers/assemblyai.md, verified 2026-07-27):
- Auth header is the bare API key — NO `Bearer` prefix (wrong format -> 1008).
- HARD constraint: audio chunks must be 50-1000ms AND paced <= realtime, or
  the socket closes 3007. send_audio() therefore coalesces sub-50ms input.
- Two transcript semantics behind one protocol: universal-streaming-* is
  immutable/accumulating, universal-3-5-pro sends true partials that
  supersede within a turn. We key on the message shape, not the model.
- format_turns=true doubles the final Turn (unformatted then formatted,
  same turn_order): only `end_of_turn && turn_is_formatted` is the final.
- Billing is WS-open session time; unclosed sessions bill up to 3 hours.
- Speaker labels are letters ("A", "B", ...) -> mapped to ints.
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
    BillingBasis,
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream

WS_BASE = "wss://streaming.assemblyai.com/v3/ws"
MIN_CHUNK_MS = 50

_ENCODING_MAP = {"linear16": "pcm_s16le", "mulaw": "pcm_mulaw", "opus": "opus",
                 "ogg-opus": "ogg_opus"}

# close codes where a fresh connection can help
_RECOVERABLE_CLOSES = {1011, 3005, 3008, 3009}

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,
    endpointing=True,
    keyterms=True,
    keyterms_max=100,
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
    realtime_pacing_required=True,
    chunk_ms_min=50,
    chunk_ms_max=1000,
    billing_basis=BillingBasis.SESSION_TIME,
)


def speaker_to_int(label: str | None) -> int | None:
    if not label:
        return None
    if label.isdigit():
        return int(label)
    if len(label) == 1 and label.isalpha():
        return ord(label.upper()) - ord("A")
    return None


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    params: list[tuple[str, str]] = [
        ("speech_model", config.model),
        ("sample_rate", str(config.sample_rate)),
        ("encoding", _ENCODING_MAP[config.encoding]),
        ("format_turns", "true"),
    ]
    if config.language:
        params.append(("language_codes", json.dumps([config.language])))
    if config.diarization:
        params.append(("speaker_labels", "true"))
    if config.keyterms:
        params.append(("keyterms_prompt", json.dumps(list(config.keyterms))))
    for key, value in config.provider_params.items():
        params.append((key, str(value)))
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_message(raw: str) -> list[STTEvent]:
    """Pure translation of one v3 frame. Raises ProviderStreamError on Error
    messages. Termination is handled by the caller (returns None sentinel via
    empty list + connection close)."""
    msg = json.loads(raw)
    msg_type = msg.get("type")
    events: list[STTEvent] = []

    if msg_type == "Turn":
        text = msg.get("transcript", "")
        if not text.strip():
            return events
        end_of_turn = bool(msg.get("end_of_turn"))
        formatted = bool(msg.get("turn_is_formatted"))
        # format_turns=true doubles the final; only the formatted one is final.
        is_final = end_of_turn and formatted
        if end_of_turn and not formatted:
            return events  # unformatted duplicate; formatted final follows
        words = [
            Word(
                w=w["text"],
                start=w["start"] / 1000.0,
                end=w["end"] / 1000.0,
                conf=w.get("confidence"),
                speaker=speaker_to_int(w.get("speaker") or msg.get("speaker_label")),
            )
            for w in msg.get("words", [])
            if w.get("start") is not None
        ]
        start = words[0].start if words else None
        end = words[-1].end if words else None
        events.append(
            Transcript(
                type="transcript",
                is_final=is_final,
                text=text,
                words=words or None,
                start=start,
                end=end,
                lang=msg.get("language_code"),
            )
        )
        if is_final and end is not None:
            events.append(UtteranceEnd(type="utterance_end", at=end))
    elif msg_type == "SpeechStarted":
        events.append(
            SpeechStarted(type="speech_started", at=float(msg.get("timestamp", 0)) / 1000.0)
        )
    elif msg_type == "Error":
        code = str(msg.get("error_code", ""))
        raise ProviderStreamError(
            f"assemblyai error {code}: {msg.get('error', '')}",
            recoverable=code in {"1011", "3005", "3008", "3009"},
            provider="assemblyai",
            code=code,
        )
    # Begin / Heartbeat / SpeakerRevision / Termination: no client events in v1.
    return events


@register_stt_stream("assemblyai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "AssemblyAISTTStream":
    if not settings.assemblyai_api_key:
        raise ProviderNotConfigured("assemblyai")
    return AssemblyAISTTStream(settings.assemblyai_api_key)


class AssemblyAISTTStream(STTStreamProvider):
    name = "assemblyai"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._buffer = bytearray()
        self._min_chunk_bytes = 0
        self._finished = False
        self._closed = False
        self._terminated = asyncio.Event()

    async def connect(self, config: STTConfig) -> None:
        # 50ms coalescing floor: provider closes 3007 on smaller chunks.
        bytes_per_ms = config.sample_rate * 2 * config.channels / 1000
        self._min_chunk_bytes = int(bytes_per_ms * MIN_CHUNK_MS)
        try:
            self._ws = await websockets.connect(
                build_url(config, self._ws_base),
                additional_headers={"Authorization": self._api_key},  # no Bearer
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"assemblyai connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("assemblyai connected", extra={"provider": self.name, "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        self._buffer.extend(chunk)
        if len(self._buffer) >= self._min_chunk_bytes:
            data = bytes(self._buffer)
            self._buffer.clear()
            await self._ws.send(data)

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                if '"Termination"' in raw:
                    self._terminated.set()
                    return
                for event in parse_message(raw):
                    yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"assemblyai closed {exc.code}: {exc.reason}",
                recoverable=exc.code in _RECOVERABLE_CLOSES,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            if self._buffer:
                await self._ws.send(bytes(self._buffer))
                self._buffer.clear()
            await self._ws.send(json.dumps({"type": "Terminate"}))
        except websockets.exceptions.ConnectionClosed:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            try:
                # Billing runs while the socket is open — always Terminate.
                if not self._finished:
                    await self._ws.send(json.dumps({"type": "Terminate"}))
            except Exception:  # noqa: BLE001
                pass
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
