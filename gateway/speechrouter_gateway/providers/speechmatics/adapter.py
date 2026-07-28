"""Speechmatics realtime STT adapter.

Protocol facts (docs/providers/speechmatics.md, verified 2026-07-27):
- Send StartRecognition once, then WAIT for RecognitionStarted before any
  audio — connect() blocks on it, honoring the base-class readiness contract.
- Audio is raw binary AddAudio frames; the server acks each with
  AudioAdded{seq_no}. We count frames ourselves (EndOfStream requires an
  exact last_seq_no) and throttle on the sent-vs-acked gap (the documented
  backpressure mechanism — the server stops reading when its buffer fills).
- AddTranscript results are immutable finals; AddPartialTranscript covers
  the span since the last final and supersedes the previous partial.
- results[] mixes word / punctuation / entity items; punctuation attaches to
  the previous word. metadata.transcript is the display text for the span.
- Speakers are "S1"/"S2"/"UU". Timestamps are already float seconds.
- Idle: server kills after 3 min without audio AND pings — we keep the
  websockets default ping_interval (20s) precisely for this.
- Error{type} then close; retry guidance only for quota/internal errors.
"""

import asyncio
import json
from collections.abc import AsyncIterator

import websockets

from ...config import Settings
from ...logging import logger
from ...protocol import Transcript, UtteranceEnd, Word
from ..base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTEvent,
    STTStreamProvider,
)
from ..registry import ProviderNotConfigured, register_stt_stream
from ..wsconnect import ws_connect

WS_BASE = "wss://global.rt.speechmatics.com/v2/"
ACK_WINDOW = 64  # max unacked AddAudio frames before send_audio blocks

_ENCODING_MAP = {"linear16": "pcm_s16le", "mulaw": "mulaw"}

_RECOVERABLE_ERRORS = {"quota_exceeded", "internal_error", "job_error", "session_timeout",
                       "idle_timeout"}

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,
    endpointing=True,
    keyterms=True,
    keyterms_max=1000,
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
)


def speaker_to_int(label: str | None) -> int | None:
    if not label or label == "UU":
        return None
    if label.startswith("S") and label[1:].isdigit():
        return int(label[1:])
    return None


def build_start_recognition(config: STTConfig) -> dict:
    transcription: dict = {
        "language": config.language or "en",
        "model": config.model,
        "enable_partials": config.interim_results,
        # Endpointing: EndOfUtterance events; trigger must stay < max_delay.
        "conversation_config": {"end_of_utterance_silence_trigger": 0.75},
    }
    if config.diarization:
        transcription["diarization"] = "speaker"
    if config.keyterms:
        transcription["additional_vocab"] = [{"content": t} for t in config.keyterms]
    transcription.update(config.provider_params)
    return {
        "message": "StartRecognition",
        "audio_format": {
            "type": "raw",
            "encoding": _ENCODING_MAP[config.encoding],
            "sample_rate": config.sample_rate,
        },
        "transcription_config": transcription,
    }


def results_to_words(results: list[dict]) -> list[Word]:
    """word items become Words; punctuation glues onto the previous word."""
    words: list[Word] = []
    for item in results:
        kind = item.get("type")
        alternatives = item.get("alternatives") or [{}]
        content = alternatives[0].get("content", "")
        if kind == "word":
            words.append(
                Word(
                    w=content,
                    start=float(item["start_time"]),
                    end=float(item["end_time"]),
                    conf=alternatives[0].get("confidence"),
                    speaker=speaker_to_int(alternatives[0].get("speaker")),
                    lang=alternatives[0].get("language"),
                )
            )
        elif kind == "punctuation" and words and item.get("attaches_to", "previous") in (
            "previous", "both",
        ):
            previous = words[-1]
            words[-1] = previous.model_copy(update={"w": previous.w + content})
    return words


def parse_message(raw: str, include_raw: bool = False) -> tuple[str, list[STTEvent] | int]:
    """Returns (kind, payload): ("events", [...]) | ("ack", seq_no) |
    ("started", []) | ("end", []) — Error raises."""
    msg = json.loads(raw)
    message = msg.get("message")

    if message == "AudioAdded":
        return "ack", int(msg.get("seq_no", 0))
    if message == "RecognitionStarted":
        return "started", []
    if message == "EndOfTranscript":
        return "end", []
    if message in ("AddTranscript", "AddPartialTranscript"):
        metadata = msg.get("metadata", {})
        text = (metadata.get("transcript") or "").strip()
        if not text:
            return "events", []
        words = results_to_words(msg.get("results", []))
        return "events", [
            Transcript(
                type="transcript",
                is_final=message == "AddTranscript",
                text=text,
                words=words or None,
                start=metadata.get("start_time"),
                end=metadata.get("end_time"),
                provider_raw=msg if include_raw else None,
            )
        ]
    if message == "EndOfUtterance":
        at = msg.get("metadata", {}).get("end_time", 0.0)
        return "events", [UtteranceEnd(type="utterance_end", at=float(at))]
    if message == "Error":
        error_type = msg.get("type", "unknown_error")
        raise ProviderStreamError(
            f"speechmatics {error_type}: {msg.get('reason', '')}",
            recoverable=error_type in _RECOVERABLE_ERRORS,
            provider="speechmatics",
            code=error_type,
        )
    return "events", []  # Warning / Info / audio events: log-only in v1


@register_stt_stream("speechmatics", capabilities=CAPABILITIES)
def build(settings: Settings) -> "SpeechmaticsSTTStream":
    if not settings.speechmatics_api_key:
        raise ProviderNotConfigured("speechmatics")
    return SpeechmaticsSTTStream(settings.speechmatics_api_key)


class SpeechmaticsSTTStream(STTStreamProvider):
    name = "speechmatics"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, ws_base: str = WS_BASE):
        self._api_key = api_key
        self._ws_base = ws_base
        self._ws: websockets.ClientConnection | None = None
        self._sent = 0
        self._acked = 0
        self._ack_cond = asyncio.Condition()
        self._finished = False
        self._closed = False
        self._include_raw = False

    async def connect(self, config: STTConfig) -> None:
        self._include_raw = config.include_raw
        try:
            self._ws = await ws_connect(
                self._ws_base,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                # default ping_interval kept intentionally: 3-min no-traffic kill
            )
            await self._ws.send(json.dumps(build_start_recognition(config)))
            # Contract: return only when the provider accepts audio.
            while True:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=15.0)
                if isinstance(raw, bytes):
                    continue
                kind, _ = parse_message(raw)
                if kind == "started":
                    break
        except ProviderStreamError:
            raise
        except Exception as exc:
            raise ProviderStreamError(
                f"speechmatics connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("speechmatics connected", extra={"provider": self.name,
                                                     "model": config.model})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        async with self._ack_cond:
            while self._sent - self._acked >= ACK_WINDOW:
                await self._ack_cond.wait()  # documented backpressure: ack lag
        await self._ws.send(chunk)
        self._sent += 1

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                kind, payload = parse_message(raw, self._include_raw)
                if kind == "ack":
                    async with self._ack_cond:
                        self._acked = max(self._acked, int(payload))  # type: ignore[arg-type]
                        self._ack_cond.notify_all()
                elif kind == "end":
                    return  # EndOfTranscript: flush complete
                elif kind == "events":
                    for event in payload:  # type: ignore[union-attr]
                        yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"speechmatics closed {exc.code}: {exc.reason}",
                recoverable=exc.code in {1011, 4005, 4006},
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(
                json.dumps({"message": "EndOfStream", "last_seq_no": self._sent})
            )
        except websockets.exceptions.ConnectionClosed:
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        async with self._ack_cond:  # release any blocked sender
            self._acked = self._sent
            self._ack_cond.notify_all()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
