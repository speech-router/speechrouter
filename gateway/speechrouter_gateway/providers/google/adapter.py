"""Google Cloud STT v2 streaming adapter (gRPC, optional [google] extra).

Facts (docs/providers/google.md): gRPC-only (no WebSocket exists); implicit
recognizer `projects/{p}/locations/{loc}/recognizers/_`; **hard 5-minute
stream cap** and 25KB per audio message; endpoint host must match the
recognizer location (chirp_3 -> us/eu multi-region hosts); word offsets are
proto Durations (timedelta via proto-plus); chirp_3 has NO word timestamps
in streaming — use chirp_2/latest_* for word timing.

Rotation: this adapter rotates the gRPC stream itself before the 5-minute
cap (ROTATE_SECONDS), bridging transcripts by adding the audio time already
fed to previous streams — invisible to the session layer.
"""
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false

import asyncio
from collections.abc import AsyncIterator
from typing import Any

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
from ..registry import ProviderNotConfigured, register_stt_stream

ROTATE_SECONDS = 270.0  # rotate at 4:30, under the 5-minute hard cap
MAX_MESSAGE_BYTES = 24 * 1024  # stay under the 25KB per-message limit

_LOCATION_BY_MODEL = {"chirp_3": "us", "chirp_2": "us-central1"}
_NO_WORD_TIMESTAMP_MODELS = {"chirp_3"}

CAPABILITIES = Capabilities(
    streaming=True,
    interim_results=True,
    word_timestamps=True,  # model-dependent; chirp_3 excluded in models.json
    diarization=False,  # not on chirp streaming
    endpointing=True,
    languages=frozenset({"auto"}),
    encodings=frozenset({"linear16"}),
)

_END = object()


def location_for(model: str) -> str:
    return _LOCATION_BY_MODEL.get(model, "global")


def endpoint_for(location: str) -> str:
    if location == "global":
        return "speech.googleapis.com"
    return f"{location}-speech.googleapis.com"


def _seconds(offset: Any) -> float | None:
    if offset is None:
        return None
    from typing import cast
    total = getattr(offset, "total_seconds", None)
    if not callable(total):
        return None
    return round(cast(float, total()), 3)


def parse_response(response: Any, offset: float) -> list[STTEvent]:
    """Duck-typed so tests can drive it without the SDK installed."""
    events: list[STTEvent] = []
    event_type = str(getattr(response, "speech_event_type", "") or "")
    if "SPEECH_ACTIVITY_BEGIN" in event_type:
        at = _seconds(getattr(response, "speech_event_offset", None)) or 0.0
        events.append(SpeechStarted(type="speech_started", at=round(offset + at, 3)))
    elif "SPEECH_ACTIVITY_END" in event_type:
        at = _seconds(getattr(response, "speech_event_offset", None)) or 0.0
        events.append(UtteranceEnd(type="utterance_end", at=round(offset + at, 3)))

    for result in getattr(response, "results", []) or []:
        alternatives = getattr(result, "alternatives", []) or []
        if not alternatives:
            continue
        alt = alternatives[0]
        text = getattr(alt, "transcript", "")
        if not text.strip():
            continue
        words = [
            Word(
                w=getattr(w, "word", ""),
                start=round(offset + (_seconds(getattr(w, "start_offset", None)) or 0.0), 3),
                end=round(offset + (_seconds(getattr(w, "end_offset", None)) or 0.0), 3),
                conf=getattr(w, "confidence", None) or None,
            )
            for w in getattr(alt, "words", []) or []
        ]
        end = _seconds(getattr(result, "result_end_offset", None))
        events.append(
            Transcript(
                type="transcript",
                is_final=bool(getattr(result, "is_final", False)),
                text=text,
                words=words or None,
                end=round(offset + end, 3) if end is not None else None,
                lang=getattr(result, "language_code", None) or None,
            )
        )
    return events


def _import_sdk():
    try:
        from google.api_core.client_options import ClientOptions  # noqa: PLC0415
        from google.cloud import speech_v2  # noqa: PLC0415
    except ImportError as exc:
        raise ProviderNotConfigured(
            "google realtime requires the [google] extra: uv add speechrouter-gateway[google]"
        ) from exc
    return speech_v2, ClientOptions


@register_stt_stream("google", capabilities=CAPABILITIES)
def build(settings: Settings) -> "GoogleSTTStream":
    if not settings.google_project_id:
        raise ProviderNotConfigured("google")
    _import_sdk()
    return GoogleSTTStream(settings.google_project_id)


class GoogleSTTStream(STTStreamProvider):
    name = "google"
    capabilities = CAPABILITIES

    def __init__(self, project_id: str):
        self._project_id = project_id
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._config: STTConfig | None = None
        self._client = None
        self._byte_rate = 32000
        self._finished = False
        self._closed = False

    async def connect(self, config: STTConfig) -> None:
        speech_v2, client_options_cls = _import_sdk()
        self._config = config
        self._byte_rate = config.sample_rate * 2 * config.channels
        location = location_for(config.model)
        try:
            self._client = speech_v2.SpeechAsyncClient(
                client_options=client_options_cls(api_endpoint=endpoint_for(location))
            )
        except Exception as exc:
            raise ProviderStreamError(
                f"google client init failed: {exc}", recoverable=False, provider=self.name
            ) from exc
        logger.info("google stt client ready", extra={"provider": self.name,
                                                      "model": config.model,
                                                      "location": location})

    def _build_config_request(self, speech_v2):
        assert self._config is not None
        config = self._config
        location = location_for(config.model)
        recognizer = f"projects/{self._project_id}/locations/{location}/recognizers/_"
        features = speech_v2.RecognitionFeatures(
            enable_word_time_offsets=config.model not in _NO_WORD_TIMESTAMP_MODELS,
        )
        recognition_config = speech_v2.RecognitionConfig(
            explicit_decoding_config=speech_v2.ExplicitDecodingConfig(
                encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=config.sample_rate,
                audio_channel_count=config.channels,
            ),
            model=config.model,
            language_codes=[config.language] if config.language else ["auto"],
            features=features,
        )
        streaming_config = speech_v2.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=speech_v2.StreamingRecognitionFeatures(
                interim_results=config.interim_results,
                enable_voice_activity_events=True,
            ),
        )
        return speech_v2.StreamingRecognizeRequest(
            recognizer=recognizer, streaming_config=streaming_config
        )

    async def send_audio(self, chunk: bytes) -> None:
        for i in range(0, len(chunk), MAX_MESSAGE_BYTES):
            await self._queue.put(chunk[i : i + MAX_MESSAGE_BYTES])

    async def events(self) -> AsyncIterator[STTEvent]:
        if self._client is None or self._config is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        speech_v2, _ = _import_sdk()
        from google.api_core import exceptions as gexc  # noqa: PLC0415

        rotation_offset = 0.0
        while True:
            stream_bytes = 0

            async def request_iter():
                nonlocal stream_bytes
                yield self._build_config_request(speech_v2)
                loop = asyncio.get_running_loop()
                deadline = loop.time() + ROTATE_SECONDS
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return  # rotate: close send side under the 5-min cap
                    try:
                        item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                    except TimeoutError:
                        return
                    if item is _END:
                        self._finished = True
                        return
                    stream_bytes += len(item)
                    yield speech_v2.StreamingRecognizeRequest(audio=item)

            try:
                responses = await self._client.streaming_recognize(requests=request_iter())
                async for response in responses:
                    for event in parse_response(response, rotation_offset):
                        yield event
            except (gexc.ServiceUnavailable, gexc.DeadlineExceeded, gexc.Aborted,
                    gexc.ResourceExhausted, gexc.InternalServerError) as exc:
                raise ProviderStreamError(
                    f"google stream failed: {exc}", recoverable=True, provider=self.name
                ) from exc
            except gexc.GoogleAPICallError as exc:
                raise ProviderStreamError(
                    f"google stream rejected: {exc}", recoverable=False, provider=self.name
                ) from exc
            if self._finished:
                return
            rotation_offset += stream_bytes / self._byte_rate
            logger.info(
                "google stream rotated",
                extra={"provider": self.name, "offset": round(rotation_offset, 1)},
            )

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        await self._queue.put(_END)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._finished = True
        await self._queue.put(_END)
