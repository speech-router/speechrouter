"""Amazon Transcribe streaming adapter (raw WS + event-stream codec).

Protocol facts (docs/providers/aws.md, verified 2026-07-27):
- Presigned SigV4 GET URL is the entire auth (no per-chunk signing on WS);
  X-Amz-Expires=300 bounds the handshake, not stream length.
- Audio and results are event-stream binary frames; end of stream is an
  empty-payload AudioEvent.
- ResultId is stable across all partials of a segment: IsPartial=true frames
  supersede each other (our interim semantics), false = immutable final. A
  final segment end doubles as the utterance boundary (no explicit VAD
  events exist).
- Items carry StartTime/EndTime as JSON doubles in seconds; punctuation
  items glue onto the previous word; Speaker is "spk_N"/"0".."29".
- Idle ~15s kills the session: the keepalive loop sends PCM silence when
  the client is quiet (billed, tiny, and the documented approach).
- provider_params are NOT forwarded: unsorted extra query params would
  break the SigV4 canonical querystring.
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
from .eventstream import EventStreamError, build_audio_event, decode_message
from .signer import presigned_url

KEEPALIVE_INTERVAL = 5.0
SILENCE_MS = 100

_ENCODING_MAP = {"linear16": "pcm", "ogg-opus": "ogg-opus", "flac": "flac"}

_RECOVERABLE_EXCEPTIONS = {"InternalFailureException", "LimitExceededException"}

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=True,
    word_timestamps=True,
    diarization=True,
    endpointing=True,  # via final-segment boundaries
    languages=frozenset({"auto"}),
    encodings=frozenset(_ENCODING_MAP),
    sample_rates=frozenset(range(8000, 48001)),
    chunk_ms_min=50,
    chunk_ms_max=200,
)


def speaker_to_int(label: str | None) -> int | None:
    if label is None:
        return None
    text = str(label)
    digits = text.removeprefix("spk_")
    return int(digits) if digits.isdigit() else None


def parse_transcript_payload(payload: dict) -> list[STTEvent]:
    events: list[STTEvent] = []
    for result in payload.get("Transcript", {}).get("Results", []):
        alternatives = result.get("Alternatives") or []
        if not alternatives:
            continue
        alt = alternatives[0]
        text = alt.get("Transcript", "")
        if not text.strip():
            continue
        words: list[Word] = []
        for item in alt.get("Items", []):
            if item.get("Type") == "pronunciation" and item.get("StartTime") is not None:
                words.append(
                    Word(
                        w=item.get("Content", ""),
                        start=float(item["StartTime"]),
                        end=float(item["EndTime"]),
                        conf=item.get("Confidence"),
                        speaker=speaker_to_int(item.get("Speaker")),
                    )
                )
            elif item.get("Type") == "punctuation" and words:
                previous = words[-1]
                words[-1] = previous.model_copy(
                    update={"w": previous.w + item.get("Content", "")}
                )
        is_final = not result.get("IsPartial", True)
        start = float(result["StartTime"]) if result.get("StartTime") is not None else None
        end = float(result["EndTime"]) if result.get("EndTime") is not None else None
        language = result.get("LanguageCode")
        events.append(
            Transcript(
                type="transcript",
                is_final=is_final,
                text=text,
                words=words or None,
                start=start,
                end=end,
                lang=language,
            )
        )
        if is_final and end is not None:
            events.append(UtteranceEnd(type="utterance_end", at=end))
    return events


@register_stt_stream("aws", capabilities=CAPABILITIES)
def build(settings: Settings) -> "AWSTranscribeStream":
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        raise ProviderNotConfigured("aws")
    return AWSTranscribeStream(
        settings.aws_access_key_id, settings.aws_secret_access_key, settings.aws_region
    )


class AWSTranscribeStream(STTStreamProvider):
    name = "aws"
    capabilities = CAPABILITIES

    def __init__(self, access_key: str, secret_key: str, region: str):
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._ws: websockets.ClientConnection | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._silence_chunk = b""
        self._last_send = 0.0
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        url = presigned_url(
            access_key=self._access_key,
            secret_key=self._secret_key,
            region=self._region,
            sample_rate=config.sample_rate,
            language_code=config.language,
            media_encoding=_ENCODING_MAP[config.encoding],
            show_speaker_label=config.diarization,
        )
        try:
            self._ws = await ws_connect(url, ping_interval=None, ping_timeout=None)
        except Exception as exc:
            raise ProviderStreamError(
                f"aws connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        if config.encoding == "linear16":
            silence_bytes = int(config.sample_rate * 2 * config.channels * SILENCE_MS / 1000)
            self._silence_chunk = b"\x00" * silence_bytes
        self._last_send = asyncio.get_running_loop().time()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info("aws transcribe connected", extra={"provider": self.name})

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        await self._ws.send(build_audio_event(chunk))
        self._last_send = asyncio.get_running_loop().time()

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._ws is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        try:
            async for raw in self._ws:
                if isinstance(raw, str):
                    continue
                try:
                    headers, payload = decode_message(raw)
                except EventStreamError as exc:
                    raise ProviderStreamError(
                        f"aws frame corrupt: {exc}", recoverable=True, provider=self.name
                    ) from exc
                message_type = headers.get(":message-type")
                if message_type == "exception":
                    exception_type = headers.get(":exception-type", "")
                    detail = payload.decode(errors="replace")[:200]
                    raise ProviderStreamError(
                        f"aws {exception_type}: {detail}",
                        recoverable=exception_type in _RECOVERABLE_EXCEPTIONS,
                        provider=self.name,
                        code=exception_type,
                    )
                if message_type == "event" and headers.get(":event-type") == "TranscriptEvent":
                    for event in parse_transcript_payload(json.loads(payload)):
                        yield event
        except websockets.exceptions.ConnectionClosedOK:
            pass
        except websockets.exceptions.ConnectionClosed as exc:
            if self._finished:
                return
            raise ProviderStreamError(
                f"aws closed {exc.code}: {exc.reason}",
                recoverable=exc.code == 1011,  # keepalive/idle timeout
                provider=self.name,
                code=str(exc.code),
            ) from exc

    async def finish(self) -> None:
        if self._finished or self._ws is None:
            return
        self._finished = True
        try:
            await self._ws.send(build_audio_event(b""))  # empty payload = EOS
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
        """AWS kills sessions ~15s without audio; stream silence during gaps."""
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if self._ws is None or self._finished or not self._silence_chunk:
                    return
                idle = asyncio.get_running_loop().time() - self._last_send
                if idle >= KEEPALIVE_INTERVAL:
                    try:
                        await self._ws.send(build_audio_event(self._silence_chunk))
                        self._last_send = asyncio.get_running_loop().time()
                    except websockets.exceptions.ConnectionClosed:
                        return
        except asyncio.CancelledError:
            pass
