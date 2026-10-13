"""WSS /v1/speak over a provider-native incremental-text socket (phase 3).

Same client protocol as tts/session.py, but instead of segmenting text and
issuing one request per sentence, text.delta frames go straight into the
provider's own socket (xAI Grok TTS, Deepgram Flux), which does its own
chunking and prosody and supports barge-in natively:

  client text.delta ──▶ stream.send_text        provider audio ──▶ audio.chunk + binary
  client clear      ──▶ stream.clear() ─ack─▶  cleared{last_seq, text_spoken?, text_remaining?}
  client finalize   ──▶ stream.finish()        audio() ends ──▶ done{usage}

While a clear is in flight, nothing reaches the client: chunks generated
before the provider's ack are dropped here as well as in the adapter.
One tts_stream usage event from run()'s finally, same contract as the
segmenting session (PLAN-tts-live.md §3.0).
"""

import asyncio
import contextlib
import json
import time
import uuid

from ..alerting import customer_facing, report_provider_failure
from ..audio.mp3_frames import Mp3DurationCounter
from ..audio.pcm_codec import PcmConverter
from ..config import Settings
from ..logging import logger
from ..metering import UsageEmitter, UsageEvent
from ..protocol import AudioChunk, Cleared, Done, Error, SessionOpen
from ..protocol.events import Code, Usage
from ..providers.base import ProviderStreamError, TTSStream
from ..router.resolver import ResolvedTTS
from .runner import list_cost, tts_units
from .session import SpeakClosed, SpeakLimit, SpeakTransport

CLEAR_ACK_TIMEOUT = 5.0


class NativeSpeakSession:
    def __init__(
        self,
        transport: SpeakTransport,
        resolved: ResolvedTTS,
        stream: TTSStream,
        emitter: UsageEmitter,
        key_id: str,
        settings: Settings,
        byok: bool = False,
        org_id: str | None = None,
        redis=None,
    ):
        self._transport = transport
        self._resolved = resolved
        self._stream = stream
        self._emitter = emitter
        self._key_id = key_id
        self._settings = settings
        self._byok = byok
        self._org_id = org_id
        self._redis = redis
        self.session_id = f"speak_{uuid.uuid4().hex[:16]}"
        self._seq = 0
        self._last_sent_seq = 0
        self._audio_time = 0.0
        self._native_bytes = 0
        self._sent_mp3 = Mp3DurationCounter() if resolved.out_format == "mp3" else None
        self._converter = (
            PcmConverter(resolved.out_format, resolved.native_rate, resolved.out_sample_rate)
            if resolved.wrap else None
        )
        self._clearing = False
        self._send_lock = asyncio.Lock()
        self._finalized = False
        self._status = "completed"
        self._started = time.monotonic()
        self._last_activity = time.monotonic()

    # ----------------------------------------------------------- lifecycle

    async def run(self) -> None:
        resolved = self._resolved
        tasks: set[asyncio.Task] = set()
        try:
            await self._stream.connect(resolved.config)
            await self._transport.send_event(SessionOpen(
                type="session.open", session_id=self.session_id, model=resolved.slug,
                encoding="linear16" if resolved.out_format == "pcm" else resolved.out_format,
                sample_rate=resolved.out_sample_rate, voice=resolved.config.voice,
            ))
            pump = asyncio.create_task(self._pump())
            tasks = {pump, asyncio.create_task(self._read_client()),
                     asyncio.create_task(self._watchdog())}
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            decisive = pump if pump in done else done.pop()
            exc = decisive.exception()
            if exc is not None:
                raise exc
            if decisive is pump:
                await self._transport.send_event(self._done_event())
            else:
                self._status = "completed" if self._finalized else "client_disconnect"
        except SpeakClosed:
            self._status = "completed" if self._finalized else "client_disconnect"
        except SpeakLimit as exc:
            self._status = exc.status
            await self._try_error(exc.code, exc.message)
        except ProviderStreamError as exc:
            self._status = "provider_error"
            report_provider_failure(exc.provider, resolved.slug, str(exc), code=exc.code)
            safe = self._byok or exc.code == "invalid_request"
            await self._try_error(Code.provider_error,
                                  str(exc) if safe else customer_facing(exc.code),
                                  provider=exc.provider)
        except Exception:
            self._status = "error"
            logger.error("native speak session crashed", exc_info=True,
                         extra={"session": self.session_id})
            await self._try_error(Code.internal_error, "internal error")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await self._stream.close()
            await asyncio.shield(self._finish())

    # -------------------------------------------------------------- client

    async def _read_client(self) -> None:
        while True:
            message = await self._transport.recv()
            self._last_activity = time.monotonic()
            if message is None:
                return
            if isinstance(message, bytes):
                continue
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                event = None
            kind = event.get("type") if isinstance(event, dict) else None
            if kind == "text.delta" and isinstance(event, dict) and not self._finalized:
                text = event.get("text")
                if isinstance(text, str) and text:
                    await self._stream.send_text(text)
            elif kind == "finalize" and not self._finalized:
                self._finalized = True
                await self._stream.finish()
            elif kind == "clear":
                playback = event.get("playback_ms") if isinstance(event, dict) else None
                await self._clear(playback if isinstance(playback, int) else None)
            elif kind != "keepalive":
                logger.info("ignoring unknown speak event",
                            extra={"session": self.session_id, "event_type": kind})

    async def _clear(self, playback_ms: int | None = None) -> None:
        self._clearing = True  # drop anything still arriving from before the ack
        try:
            async with asyncio.timeout(CLEAR_ACK_TIMEOUT):
                info = await self._stream.clear(playback_ms)
        except TimeoutError:
            info = {}
            logger.warning("provider clear ack timed out", extra={"session": self.session_id})
        finally:
            self._clearing = False
        fields = {k: v for k, v in (info or {}).items()
                  if k in ("text_spoken", "text_remaining") and isinstance(v, str)}
        async with self._send_lock:
            await self._transport.send_event(
                Cleared(type="cleared", last_seq=self._last_sent_seq, **fields))

    # -------------------------------------------------------------- audio

    async def _pump(self) -> None:
        async for chunk in self._stream.audio():
            if self._clearing or not chunk:
                continue
            self._native_bytes += len(chunk)
            out = self._converter.feed(chunk) if self._converter else chunk
            if out:
                await asyncio.shield(self._send_pair(out))
        if self._converter is not None:
            tail = self._converter.flush()
            if tail:
                await self._send_pair(tail)

    async def _send_pair(self, audio: bytes) -> None:
        async with self._send_lock:
            self._seq += 1
            await self._transport.send_event(
                AudioChunk(type="audio.chunk", seq=self._seq, start=round(self._audio_time, 3)))
            await self._transport.send_audio(audio)
            self._last_sent_seq = self._seq
            self._last_activity = time.monotonic()
            fmt, rate = self._resolved.out_format, self._resolved.out_sample_rate
            if fmt == "pcm":
                self._audio_time += len(audio) / (2 * rate)
            elif fmt in {"mulaw", "alaw"}:
                self._audio_time += len(audio) / rate
            elif self._sent_mp3 is not None:
                self._sent_mp3.feed(audio)
                self._audio_time = self._sent_mp3.seconds

    # ------------------------------------------------------------ watchdog

    async def _watchdog(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(1.0)
            tick += 1
            now = time.monotonic()
            if tick % 30 == 0:
                await self._check_credits()
            if now - self._started > self._settings.max_session_seconds:
                raise SpeakLimit(Code.session_expired, "session_expired",
                                 "maximum session duration reached")
            if now - self._last_activity > self._settings.idle_timeout_seconds:
                raise SpeakLimit(Code.audio_timeout, "audio_timeout",
                                 "no text or keepalive received; closing idle session")

    async def _check_credits(self) -> None:
        if self._byok or self._redis is None or not self._org_id:
            return
        try:
            raw = await self._redis.get(f"speechrouter:balance:{self._org_id}")
        except Exception:  # noqa: BLE001 - fail open
            return
        if raw is None:
            return
        cost = list_cost(self._resolved.entry, self._units(), False)
        if int(raw) - cost * 1_000_000 <= 0:
            raise SpeakLimit(Code.insufficient_credits, "insufficient_credits",
                             "credit balance exhausted mid-session — "
                             "top up at speechrouter.ai/settings/billing")

    # --------------------------------------------------------------- usage

    def _units(self) -> dict[str, float]:
        return tts_units(self._resolved.entry, self._stream.usage,
                         produced=self._native_bytes > 0)

    def _seconds(self) -> float:
        fmt, rate = self._resolved.config.format, self._resolved.native_rate
        if fmt == "pcm":
            return self._native_bytes / (2 * rate)
        if fmt in {"mulaw", "alaw"}:
            return self._native_bytes / rate
        return self._audio_time

    def _done_event(self) -> Done:
        units = self._units()
        seconds = round(self._seconds(), 3)
        return Done(type="done", usage=Usage(
            audio_seconds=seconds, characters=self._stream.usage.characters,
            model=self._resolved.slug, cost_usd=list_cost(self._resolved.entry, units, self._byok),
            output_audio_seconds=seconds, units=units,
        ))

    async def _finish(self) -> None:
        units = self._units()
        seconds = round(self._seconds(), 3)
        logger.info("native speak session finished", extra={
            "session": self.session_id, "model": self._resolved.slug, "status": self._status,
            "characters": self._stream.usage.characters, "audio_seconds": seconds,
            "units": units,
        })
        with contextlib.suppress(Exception):
            await self._emitter.emit(UsageEvent(
                session_id=self.session_id, key_id=self._key_id, model=self._resolved.slug,
                kind="tts_stream", audio_seconds=seconds, billed_seconds=0.0,
                billing_basis="units", characters=self._stream.usage.characters,
                status=self._status, byok=self._byok, units=units,
                units_estimated=self._stream.usage.estimated,
                session_seconds=round(time.monotonic() - self._started, 3),
                output_audio_seconds=seconds,
                list_cost_usd=list_cost(self._resolved.entry, units, self._byok),
            ))

    async def _try_error(self, code: Code, message: str, provider: str | None = None) -> None:
        with contextlib.suppress(SpeakClosed):
            await self._transport.send_event(Error(
                type="error", code=code, message=message, provider=provider, recoverable=False))
