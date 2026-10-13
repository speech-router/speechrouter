"""WSS /v1/speak session: incremental text in, binary audio out.

Protocol (packages/spec/events.schema.json, spec README decision 5):
  client -> text.delta{text} | finalize | clear | keepalive
  server -> session.open, then per audio frame: audio.chunk{seq,start} text
            frame immediately followed by ONE binary frame; cleared{last_seq};
            done{usage}; error

Request/response vendors (OpenAI, Gemini) have no incremental-text socket,
so the session does the streaming itself (PLAN §1.1 B):

  text.delta ─▶ TextSegmenter ─▶ segment queue ─▶ pipeline ─▶ client
                                                   │
                         one synthesis job per segment, at most PREFETCH
                         running ahead of the one being sent; output order
                         is always segment order

`clear` (barge-in) bumps the epoch: in-flight jobs are cancelled, queued
segments and pending text are dropped, and `cleared{last_seq}` tells the
client which chunks are stale. Audio a cancelled job already generated was
paid for upstream, so its usage still counts.

Usage: ONE event (kind tts_stream) from run()'s finally, summing every
dispatched segment. Contract: PLAN-tts-live.md §3.0.
"""

import asyncio
import contextlib
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from ..alerting import customer_facing, report_provider_failure
from ..audio.mp3_frames import Mp3DurationCounter
from ..config import Settings
from ..logging import logger
from ..metering import UsageEmitter, UsageEvent
from ..protocol import AudioChunk, Cleared, Done, Error, SessionOpen
from ..protocol.events import Code, Usage
from ..providers.base import ProviderStreamError, TTSProvider
from ..router.resolver import ResolvedTTS
from .runner import TTSRun, list_cost, tts_units
from .segmenter import TextSegmenter

PREFETCH = 1  # segments synthesized ahead of the one being sent
STALE_SECONDS = 0.4  # producer pause after which a long clause is cut
_FINAL = object()


class SpeakClosed(Exception):
    """Client is gone."""


class SpeakLimit(Exception):
    def __init__(self, code: Code, status: str, message: str):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


class SpeakTransport(Protocol):
    async def recv(self) -> bytes | str | None: ...
    async def send_event(self, event: BaseModel) -> None: ...
    async def send_audio(self, data: bytes) -> None: ...


@dataclass
class _Job:
    text: str
    run: TTSRun
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


class SpeakSession:
    def __init__(
        self,
        transport: SpeakTransport,
        resolved: ResolvedTTS,
        emitter: UsageEmitter,
        key_id: str,
        settings: Settings,
        byok: bool = False,
        org_id: str | None = None,
        redis=None,
    ):
        self._transport = transport
        self._resolved = resolved
        self._emitter = emitter
        self._key_id = key_id
        self._settings = settings
        self._byok = byok
        self._org_id = org_id
        self._redis = redis
        self._adapter: TTSProvider = resolved.build()
        self.session_id = f"speak_{uuid.uuid4().hex[:16]}"
        self._segmenter = TextSegmenter(max_chars=resolved.max_input_chars)
        self._segments: asyncio.Queue = asyncio.Queue()
        self._jobs: deque[_Job] = deque()
        self._finished_runs: list[TTSRun] = []
        self._seq = 0
        self._last_sent_seq = 0
        self._audio_time = 0.0  # seconds of audio sent (audio.chunk.start)
        self._inner: asyncio.Task | None = None  # current pipeline; replaced on clear
        self._restart = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._sent_mp3 = Mp3DurationCounter() if resolved.out_format == "mp3" else None
        self._finalized = False
        self._status = "completed"
        self._started = time.monotonic()
        self._last_activity = time.monotonic()
        self._last_delta = 0.0

    # ----------------------------------------------------------- lifecycle

    async def run(self) -> None:
        resolved = self._resolved
        try:
            await self._transport.send_event(SessionOpen(
                type="session.open", session_id=self.session_id, model=resolved.slug,
                encoding=_WIRE_ENCODING.get(resolved.out_format, resolved.out_format),
                sample_rate=resolved.out_sample_rate, voice=resolved.config.voice,
            ))
        except SpeakClosed:
            self._status = "client_disconnect"
            await self._finish()
            return

        pipeline = asyncio.create_task(self._supervise())
        reader = asyncio.create_task(self._read_client())
        watchdog = asyncio.create_task(self._watchdog())
        tasks = (pipeline, reader, watchdog)
        try:
            done, _ = await asyncio.wait(set(tasks), return_when=asyncio.FIRST_COMPLETED)
            decisive = pipeline if pipeline in done else done.pop()
            exc = decisive.exception()
            if exc is not None:
                raise exc
            if decisive is pipeline:
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
            logger.error("speak session crashed", exc_info=True,
                         extra={"session": self.session_id})
            await self._try_error(Code.internal_error, "internal error")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._cancel_jobs()
            await self._finish()

    # -------------------------------------------------------------- client

    async def _read_client(self) -> None:
        while True:
            message = await self._transport.recv()
            self._last_activity = time.monotonic()
            if message is None:
                return
            if isinstance(message, bytes):
                continue  # /v1/speak takes no client audio
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                event = None
            kind = event.get("type") if isinstance(event, dict) else None
            if kind == "text.delta" and isinstance(event, dict) and not self._finalized:
                text = event.get("text")
                if isinstance(text, str) and text:
                    self._last_delta = time.monotonic()
                    for segment in self._segmenter.push(text):
                        self._segments.put_nowait(segment)
            elif kind == "finalize" and not self._finalized:
                self._finalized = True
                tail = self._segmenter.flush()
                if tail:
                    self._segments.put_nowait(tail)
                self._segments.put_nowait(_FINAL)
            elif kind == "clear":
                await self._clear()
            elif kind == "keepalive":
                pass
            else:
                logger.info("ignoring unknown speak event",
                            extra={"session": self.session_id, "event_type": kind})

    async def _clear(self) -> None:
        inner = self._inner
        if inner is not None and not inner.done():
            inner.cancel()
            await asyncio.wait({inner})
        await self._cancel_jobs()
        self._segmenter.clear()
        finalized = False
        while not self._segments.empty():
            if self._segments.get_nowait() is _FINAL:
                finalized = True
        async with self._send_lock:
            await self._transport.send_event(
                Cleared(type="cleared", last_seq=self._last_sent_seq)
            )
        if finalized:
            self._segments.put_nowait(_FINAL)  # clear doesn't undo a finalize
        self._restart.set()

    # ------------------------------------------------------------ pipeline

    async def _supervise(self) -> None:
        """Owns the pipeline across clears. asyncio.wait (not await) keeps an
        inner cancellation — a barge-in — from looking like our own."""
        try:
            while True:
                self._restart.clear()
                self._inner = asyncio.create_task(self._pipeline())
                await asyncio.wait({self._inner})
                if not self._inner.cancelled():
                    self._inner.result()  # re-raises provider errors
                    return
                await self._restart.wait()
        finally:
            if self._inner is not None:
                self._inner.cancel()
                await asyncio.wait({self._inner})

    async def _pipeline(self) -> None:
        finalizing = False
        while True:
            # top up: start jobs for segments already queued
            while len(self._jobs) <= PREFETCH and not self._segments.empty():
                item = self._segments.get_nowait()
                if item is _FINAL:
                    finalizing = True
                    break
                self._start_job(item)
            if not self._jobs:
                if finalizing:
                    return
                item = await self._segments.get()
                if item is _FINAL:
                    return
                self._start_job(item)
                continue
            await self._send_job(self._jobs[0])
            self._finished_runs.append(self._jobs.popleft().run)

    def _start_job(self, text: str) -> None:
        job = _Job(text=text, run=TTSRun(self._resolved))
        job.task = asyncio.create_task(self._produce(job))
        self._jobs.append(job)

    async def _produce(self, job: _Job) -> None:
        stream = job.run.stream(self._adapter, job.text)
        try:
            async for chunk in stream:
                await job.queue.put(chunk)
            await job.queue.put(None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - delivered to the sender in order
            await job.queue.put(exc)
        finally:
            await stream.aclose()  # type: ignore[attr-defined]

    async def _send_job(self, job: _Job) -> None:
        while True:
            item = await job.queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            # shielded: a barge-in must never split a chunk header from its audio
            await asyncio.shield(self._send_pair(item, job))
            # more text may have been segmented while we were sending
            while len(self._jobs) <= PREFETCH and not self._segments.empty():
                peek = self._segments.get_nowait()
                if peek is _FINAL:
                    # put back in front: re-queue preserves order (queue is FIFO
                    # and nothing else is queued after a finalize)
                    self._segments.put_nowait(_FINAL)
                    break
                self._start_job(peek)

    async def _send_pair(self, audio: bytes, job: _Job) -> None:
        async with self._send_lock:
            self._seq += 1
            await self._transport.send_event(
                AudioChunk(type="audio.chunk", seq=self._seq, start=round(self._audio_time, 3))
            )
            await self._transport.send_audio(audio)
            self._last_sent_seq = self._seq
            self._last_activity = time.monotonic()
            self._advance_clock(audio)

    def _advance_clock(self, audio: bytes) -> None:
        """audio.chunk.start counts audio SENT (producers run ahead)."""
        fmt, rate = self._resolved.out_format, self._resolved.out_sample_rate
        if fmt == "pcm":
            self._audio_time += len(audio) / (2 * rate)
        elif fmt in {"mulaw", "alaw"}:
            self._audio_time += len(audio) / rate
        elif self._sent_mp3 is not None:
            self._sent_mp3.feed(audio)
            self._audio_time = self._sent_mp3.seconds

    async def _cancel_jobs(self) -> None:
        jobs = list(self._jobs)
        self._jobs.clear()
        for job in jobs:
            if job.task is not None:
                job.task.cancel()
        await asyncio.gather(*(j.task for j in jobs if j.task is not None),
                             return_exceptions=True)
        self._finished_runs.extend(j.run for j in jobs)

    # ------------------------------------------------------------ watchdog

    async def _watchdog(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(0.1)
            tick += 1
            now = time.monotonic()
            if (self._last_delta and now - self._last_delta > STALE_SECONDS
                    and not self._finalized):
                stale = self._segmenter.take_stale()
                if stale:
                    self._segments.put_nowait(stale)
            if tick % 300 == 0:
                await self._check_credits()
            if now - self._started > self._settings.max_session_seconds:
                raise SpeakLimit(Code.session_expired, "session_expired",
                                 "maximum session duration reached")
            busy = bool(self._jobs) or not self._segments.empty()
            if not busy and now - self._last_activity > self._settings.idle_timeout_seconds:
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
        units, _ = self._totals()
        if int(raw) - list_cost(self._resolved.entry, units, False) * 1_000_000 <= 0:
            raise SpeakLimit(Code.insufficient_credits, "insufficient_credits",
                             "credit balance exhausted mid-session — "
                             "top up at speechrouter.ai/settings/billing")

    # --------------------------------------------------------------- usage

    def _runs(self) -> list[TTSRun]:
        return self._finished_runs + [j.run for j in self._jobs]

    def _totals(self) -> tuple[dict[str, float], int]:
        units: dict[str, float] = {}
        characters = 0
        for run in self._runs():
            characters += run.usage.characters
            for key, value in tts_units(self._resolved.entry, run.usage,
                                        produced=run.produced_bytes > 0).items():
                units[key] = units.get(key, 0.0) + value
        return units, characters

    def _done_event(self) -> Done:
        units, characters = self._totals()
        seconds = round(sum(r.audio_seconds for r in self._runs()), 3)
        return Done(type="done", usage=Usage(
            audio_seconds=seconds, characters=characters, model=self._resolved.slug,
            cost_usd=list_cost(self._resolved.entry, units, self._byok),
            output_audio_seconds=seconds, units=units,
        ))

    async def _finish(self) -> None:
        await self._adapter.close()
        units, characters = self._totals()
        seconds = round(sum(r.audio_seconds for r in self._runs()), 3)
        cost = list_cost(self._resolved.entry, units, self._byok)
        logger.info("speak session finished", extra={
            "session": self.session_id, "model": self._resolved.slug, "status": self._status,
            "characters": characters, "audio_seconds": seconds, "units": units,
        })
        with contextlib.suppress(Exception):
            await self._emitter.emit(UsageEvent(
                session_id=self.session_id,
                key_id=self._key_id,
                model=self._resolved.slug,
                kind="tts_stream",
                audio_seconds=seconds,
                billed_seconds=0.0,
                billing_basis="units",
                characters=characters,
                status=self._status,
                byok=self._byok,
                units=units,
                units_estimated=any(r.usage.estimated for r in self._runs()),
                session_seconds=round(time.monotonic() - self._started, 3),
                output_audio_seconds=seconds,
                list_cost_usd=cost,
            ))

    async def _try_error(self, code: Code, message: str, provider: str | None = None) -> None:
        with contextlib.suppress(SpeakClosed):
            await self._transport.send_event(Error(
                type="error", code=code, message=message, provider=provider, recoverable=False,
            ))


# wire name for session.open.encoding (the query param vocabulary)
_WIRE_ENCODING = {"pcm": "linear16"}
