"""Azure AI Speech realtime adapter (Speech SDK bridge).

The USP WebSocket protocol is undocumented, so realtime Azure requires the
`azure-cognitiveservices-speech` SDK (optional extra: `speechrouter-gateway[azure]`).
The SDK is callback-based on its own threads; this adapter bridges callbacks
into an asyncio.Queue consumed by events() — the pattern proven in scribemd
production.

Facts (docs/providers/azure.md): timestamps are 100-ns ticks (/1e7 -> s);
word timings appear ONLY on finals via the Detailed-format result JSON
(NBest[0].Words); diarization needs ConversationTranscriber (speaker ids
"Guest-1"/"Unknown"); PushAudioInputStream wants PCM s16le mono 8k/16k;
stream.close() signals end of audio.
"""
# pyright: reportMissingImports=false

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

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

TICKS_PER_SECOND = 10_000_000

CAPABILITIES = Capabilities(
    streaming=True,
    batch=True,
    interim_results=True,
    word_timestamps=True,  # finals only — documented Azure limitation
    diarization=True,
    endpointing=True,
    keyterms=True,
    keyterms_max=500,
    languages=frozenset({"auto"}),
    encodings=frozenset({"linear16"}),
    sample_rates=frozenset({8000, 16000}),
)

_END = object()  # queue sentinel


def ticks_to_seconds(ticks: int | float) -> float:
    return round(float(ticks) / TICKS_PER_SECOND, 3)


def speaker_to_int(speaker_id: str | None) -> int | None:
    if not speaker_id or speaker_id == "Unknown":
        return None
    digits = "".join(c for c in str(speaker_id) if c.isdigit())
    return int(digits) if digits else None


def parse_detailed_json(
    raw: str, speaker_id: str | None = None, include_raw: bool = False
) -> Transcript | None:
    """Detailed-format final result JSON -> final Transcript with words."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    nbest = payload.get("NBest") or []
    best = nbest[0] if nbest else {}
    text = best.get("Display") or payload.get("DisplayText") or ""
    if not text.strip():
        return None
    speaker = speaker_to_int(speaker_id)
    words = [
        Word(
            w=w.get("Word", ""),
            start=ticks_to_seconds(w["Offset"]),
            end=ticks_to_seconds(w["Offset"] + w.get("Duration", 0)),
            conf=best.get("Confidence"),
            speaker=speaker,
        )
        for w in best.get("Words") or []
        if w.get("Offset") is not None
    ]
    offset = payload.get("Offset")
    duration = payload.get("Duration", 0)
    start = ticks_to_seconds(offset) if offset is not None else None
    end = ticks_to_seconds(offset + duration) if offset is not None else None
    return Transcript(
        type="transcript",
        is_final=True,
        text=text,
        words=words or None,
        start=start,
        end=end,
        provider_raw=payload if include_raw else None,
    )


def _import_sdk():
    try:
        import azure.cognitiveservices.speech as speechsdk  # noqa: PLC0415
    except ImportError as exc:
        raise ProviderNotConfigured(
            "azure realtime requires the [azure] extra: uv add speechrouter-gateway[azure]"
        ) from exc
    return speechsdk


@register_stt_stream("azure", capabilities=CAPABILITIES)
def build(settings: Settings) -> "AzureSTTStream":
    if not settings.azure_speech_key or not settings.azure_speech_region:
        raise ProviderNotConfigured("azure")
    _import_sdk()  # fail at resolve time, not mid-connect
    return AzureSTTStream(settings.azure_speech_key, settings.azure_speech_region)


class AzureSTTStream(STTStreamProvider):
    name = "azure"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, region: str):
        self._api_key = api_key
        self._region = region
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream = None
        self._recognizer = None
        self._finished = False
        self._closed = False
        self._include_raw = False

    async def connect(self, config: STTConfig) -> None:
        self._include_raw = config.include_raw
        speechsdk = _import_sdk()
        self._loop = asyncio.get_running_loop()
        try:
            speech_config = speechsdk.SpeechConfig(
                subscription=self._api_key, region=self._region
            )
            speech_config.request_word_level_timestamps()
            speech_config.output_format = speechsdk.OutputFormat.Detailed
            audio_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=config.sample_rate, bits_per_sample=16,
                channels=config.channels,
            )
            self._stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
            audio_config = speechsdk.audio.AudioConfig(stream=self._stream)

            if config.diarization:
                recognizer = speechsdk.transcription.ConversationTranscriber(
                    speech_config=speech_config, audio_config=audio_config,
                    language=config.language or "en-US",
                )
                recognizer.transcribing.connect(self._on_interim)
                recognizer.transcribed.connect(self._on_final)
                recognizer.canceled.connect(self._on_canceled)
                recognizer.session_stopped.connect(self._on_stopped)
                self._recognizer = recognizer
                await asyncio.to_thread(lambda: recognizer.start_transcribing_async().get())
            else:
                recognizer = speechsdk.SpeechRecognizer(
                    speech_config=speech_config, audio_config=audio_config,
                    language=config.language or "en-US",
                )
                if config.keyterms:
                    grammar = speechsdk.PhraseListGrammar.from_recognizer(recognizer)
                    for term in config.keyterms:
                        grammar.addPhrase(term)
                recognizer.recognizing.connect(self._on_interim)
                recognizer.recognized.connect(self._on_final)
                recognizer.canceled.connect(self._on_canceled)
                recognizer.session_stopped.connect(self._on_stopped)
                self._recognizer = recognizer
                await asyncio.to_thread(
                    lambda: recognizer.start_continuous_recognition_async().get()
                )
        except ProviderStreamError:
            raise
        except Exception as exc:
            raise ProviderStreamError(
                f"azure connect failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        logger.info("azure realtime connected", extra={"provider": self.name})

    # SDK callbacks run on SDK threads: hop to the loop via call_soon_threadsafe.
    def _put(self, item: Any) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, item)

    def _on_interim(self, evt: Any) -> None:
        text = evt.result.text
        if text and text.strip():
            self._put(
                Transcript(
                    type="transcript",
                    is_final=False,
                    text=text,
                    start=ticks_to_seconds(evt.result.offset),
                )
            )

    def _on_final(self, evt: Any) -> None:
        speaker = getattr(evt.result, "speaker_id", None)
        transcript = parse_detailed_json(evt.result.json, speaker, self._include_raw)
        if transcript is not None:
            self._put(transcript)

    def _on_canceled(self, evt: Any) -> None:
        details = getattr(evt, "error_details", "") or str(getattr(evt, "reason", ""))
        if self._finished:
            self._put(_END)
            return
        self._put(
            ProviderStreamError(
                f"azure canceled: {details}", recoverable=True, provider=self.name
            )
        )

    def _on_stopped(self, evt: Any) -> None:
        self._put(_END)

    async def send_audio(self, chunk: bytes) -> None:
        if self._stream is None:
            raise ProviderStreamError(
                "send before connect", recoverable=False, provider=self.name
            )
        self._stream.write(chunk)  # non-blocking buffer write

    async def events(self) -> AsyncIterator[STTEvent]:
        while True:
            item = await self._queue.get()
            if item is _END:
                return
            if isinstance(item, ProviderStreamError):
                raise item
            yield item

    async def finish(self) -> None:
        if self._finished or self._stream is None:
            return
        self._finished = True
        self._stream.close()  # EOS -> recognition drains -> session_stopped

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        recognizer = self._recognizer
        if recognizer is not None:
            try:
                stop = getattr(recognizer, "stop_continuous_recognition_async", None) or getattr(
                    recognizer, "stop_transcribing_async", None
                )
                if stop is not None:
                    await asyncio.to_thread(lambda: stop().get())
            except Exception:  # noqa: BLE001 - teardown must never raise
                pass
        self._put(_END)
