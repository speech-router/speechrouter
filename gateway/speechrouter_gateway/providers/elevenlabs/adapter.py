"""ElevenLabs Scribe v2 Realtime adapter.

Protocol facts (docs/providers/elevenlabs.md, verified 2026-07-27):
- Audio is BASE64 inside input_audio_chunk JSON messages (no binary frames).
- audio_format encodes rate: pcm_16000, ulaw_8000, ... (map from config).
- commit_strategy=vad auto-commits on silence; a chunk with commit=true
  forces one (used by finish()).
- Words carry type word|spacing|audio_event — only `word` items become
  Words; speaker_id like "speaker_1" maps to int.
- Error message_types are a closed enum; recoverability mapped per type.
- No explicit end-of-stream event: finish() force-commits, then events()
  drains with a grace timeout (same pattern as OpenAI realtime).
"""

import asyncio
import base64
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
from ..wsconnect import ws_connect

WS_BASE = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
DRAIN_TIMEOUT = 5.0

_RECOVERABLE_ERRORS = {"rate_limited", "quota_exceeded", "queue_overflow",
                       "resource_exhausted", "commit_throttled", "transcriber_error", "error"}

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,  # speaker_id on words (batch); realtime timestamps opt-in
    endpointing=True,  # vad commit strategy
    keyterms=True,
    keyterms_max=50,
    languages=frozenset({"auto"}),
    encodings=frozenset({"linear16", "mulaw"}),
    sample_rates=frozenset({8000, 16000, 22050, 24000, 44100, 48000}),
)


def audio_format_for(encoding: str, sample_rate: int) -> str:
    if encoding == "mulaw":
        return "ulaw_8000"
    return f"pcm_{sample_rate}"


def speaker_to_int(speaker_id: str | None) -> int | None:
    if not speaker_id:
        return None
    digits = "".join(c for c in speaker_id if c.isdigit())
    return int(digits) if digits else None


def build_url(config: STTConfig, base: str = WS_BASE) -> str:
    params: list[tuple[str, str]] = [
        ("model_id", config.model),
        ("audio_format", audio_format_for(config.encoding, config.sample_rate)),
        ("commit_strategy", "vad"),
        ("include_timestamps", "true"),
    ]
    if config.language:
        params.append(("language_code", config.language))
    if config.keyterms:
        params.extend(("keyterms[]", t) for t in config.keyterms)
    for key, value in config.provider_params.items():
        params.append((key, str(value)))
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_message(raw: str, include_raw: bool = False) -> list[STTEvent]:
    msg = json.loads(raw)
    kind = msg.get("message_type", "")
    if kind == "partial_transcript":
        text = msg.get("text", "")
        return (
            [Transcript(type="transcript", is_final=False, text=text,
                        provider_raw=msg if include_raw else None)] if text.strip() else []
        )
    if kind in ("committed_transcript", "final_transcript"):
        # ElevenLabs sends BOTH the plain commit and its _with_timestamps
        # sibling for the same audio; we always request timestamps, so the
        # plain one is a duplicate — drop it or every final doubles.
        return []
    if kind in ("committed_transcript_with_timestamps", "final_transcript_with_timestamps"):
        text = msg.get("text", "")
        if not text.strip():
            return []
        words = [
            Word(
                w=w["text"],
                start=float(w["start"]),
                end=float(w["end"]),
                conf=None,
                speaker=speaker_to_int(w.get("speaker_id")),
            )
            for w in msg.get("words") or []
            if w.get("type") == "word" and w.get("start") is not None
        ]
        return [
            Transcript(
                type="transcript",
                is_final=True,
                text=text,
                words=words or None,
                start=words[0].start if words else None,
                end=words[-1].end if words else None,
                lang=msg.get("language_code"),
                provider_raw=msg if include_raw else None,
            )
        ]
    if kind in {"error", "auth_error", "quota_exceeded", "commit_throttled", "unaccepted_terms",
                "rate_limited", "queue_overflow", "resource_exhausted",
                "session_time_limit_exceeded", "input_error", "chunk_size_exceeded",
                "insufficient_audio_activity", "transcriber_error"}:
        raise ProviderStreamError(
            f"elevenlabs {kind}: {msg.get('error', '')}",
            recoverable=kind in _RECOVERABLE_ERRORS,
            provider="elevenlabs",
            code=kind,
        )
    return []  # session_started, entities, etc.


@register_stt_stream("elevenlabs", capabilities=CAPABILITIES)
def build(settings: Settings) -> "ElevenLabsSTTStream":
    if not settings.elevenlabs_api_key:
        raise ProviderNotConfigured("elevenlabs")
    return ElevenLabsSTTStream(settings.elevenlabs_api_key)


class ElevenLabsSTTStream(STTStreamProvider):
    name = "elevenlabs"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._sample_rate = 16000
        self._finished = False
        self._closed = False
        self._include_raw = False

    async def connect(self, config: STTConfig) -> None:
        self._include_raw = config.include_raw
        self._sample_rate = config.sample_rate
        try:
            self._ws = await ws_connect(
                build_url(config, self._ws_base),
                additional_headers={"xi-api-key": self._api_key},
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"elevenlabs connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("elevenlabs connected", extra={"provider": self.name, "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        await self._ws.send(
            json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(chunk).decode(),
                    "sample_rate": self._sample_rate,
                }
            )
        )

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            while True:
                if self._finished:
                    try:
                        raw = await asyncio.wait_for(self._ws.recv(), timeout=DRAIN_TIMEOUT)
                    except TimeoutError:
                        return
                else:
                    raw = await self._ws.recv()
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
                f"elevenlabs closed {exc.code}: {exc.reason}",
                recoverable=exc.code != 1008,
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(
                json.dumps(
                    {"message_type": "input_audio_chunk", "audio_base_64": "", "commit": True,
                     "sample_rate": self._sample_rate}
                )
            )
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
