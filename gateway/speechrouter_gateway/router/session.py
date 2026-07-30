"""Streaming STT session: the pump loop with mid-stream failover.

One STTSession per client WebSocket. Structure:

  client reader ──▶ AudioRing ──▶ provider feeder ──▶ adapter
                                                        │
  client ◀── normalize (offset + dedup) ◀── drain ◀── events

The reader and watchdog live for the whole session; the feeder/drain pair is
recreated per provider attempt. On a recoverable ProviderStreamError the loop
builds the next attempt, replays the ring buffer, emits provider_switched,
and keeps going. The dedup guarantee (spec: clients never receive duplicate
finals for replayed audio) is enforced here via last_final_end.

Usage is emitted exactly once from run()'s finally — every exit path counts.
"""

import asyncio
import contextlib
import time
import uuid
from typing import Protocol

from pydantic import BaseModel

from ..alerting import report_provider_failure
from ..audio import AudioRing, bytes_per_second
from ..config import Settings
from ..logging import logger
from ..metering import UsageEmitter, UsageEvent
from ..protocol import (
    Done,
    Error,
    ProviderSwitched,
    SessionOpen,
    SpeechStarted,
    Transcript,
    UtteranceEnd,
)
from ..protocol.events import Code, Usage
from ..providers.base import ProviderStreamError, STTStreamProvider
from .resolver import ResolvedAttempt

_EPS = 1e-6


class SessionClosed(Exception):
    """Client is gone; stop everything, still meter usage."""


class SessionLimit(Exception):
    def __init__(self, code: Code, status: str, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class ClientTransport(Protocol):
    async def recv(self) -> bytes | str | None:
        """Next client frame: bytes=audio, str=JSON event, None=disconnected."""
        ...

    async def send_event(self, event: BaseModel) -> None:
        """Serialize one protocol event to the client. Raises SessionClosed."""
        ...


class STTSession:
    def __init__(
        self,
        transport: ClientTransport,
        attempts: list[ResolvedAttempt],
        emitter: UsageEmitter,
        key_id: str,
        settings: Settings,
        byok: bool = False,
    ):
        assert attempts, "resolver guarantees at least one attempt"
        self._transport = transport
        self._attempts = attempts
        self._emitter = emitter
        self._key_id = key_id
        self._byok = byok
        self._settings = settings
        primary = attempts[0].config
        self._ring = AudioRing(
            max_seconds=settings.ring_buffer_seconds,
            byte_rate=bytes_per_second(primary.encoding, primary.sample_rate, primary.channels),
        )
        self._session_id = f"sess_{uuid.uuid4().hex[:16]}"
        self._last_final_end = -1.0
        self._last_utterance_end = -1.0
        self._switches = 0
        self._status = "completed"
        self._finalized = False
        self._started = time.monotonic()
        self._last_activity = time.monotonic()

    async def run(self) -> None:
        primary = self._attempts[0]
        try:
            await self._transport.send_event(
                SessionOpen(
                    type="session.open",
                    session_id=self._session_id,
                    model=primary.slug,
                    encoding=primary.config.encoding,
                    sample_rate=primary.config.sample_rate,
                )
            )
        except SessionClosed:
            self._status = "client_disconnect"
            await self._emit_usage()
            return

        provider = asyncio.create_task(self._provider_loop())
        reader = asyncio.create_task(self._read_client())
        watchdog = asyncio.create_task(self._watchdog())
        all_tasks = {provider, reader, watchdog}
        try:
            done, _ = await asyncio.wait(all_tasks, return_when=asyncio.FIRST_COMPLETED)
            # Priority: a finished provider loop defines the outcome; otherwise
            # the reader (disconnect) or watchdog (limit) does.
            decisive = provider if provider in done else done.pop()
            exc = decisive.exception()
            if exc is not None:
                raise exc
            if decisive is provider:
                await self._transport.send_event(
                    Done(
                        type="done",
                        usage=Usage(
                            audio_seconds=round(self._ring.audio_seconds, 3),
                            model=primary.slug,
                        ),
                    )
                )
            else:  # reader returned without exception: clean disconnect
                self._status = "client_disconnect"
        except SessionClosed:
            self._status = "client_disconnect"
        except SessionLimit as exc:
            self._status = exc.status
            await self._try_send_error(exc.code, exc.message)
        except ProviderStreamError as exc:
            self._status = "provider_error"
            code = Code.all_providers_failed if self._switches else Code.provider_error
            report_provider_failure(
                exc.provider, self._attempts[0].slug, str(exc), code=code.value
            )
            await self._try_send_error(code, str(exc), provider=exc.provider)
        except Exception:
            self._status = "error"
            logger.error("session crashed", exc_info=True, extra={"session": self._session_id})
            await self._try_send_error(Code.internal_error, "internal error")
        finally:
            for task in all_tasks:
                task.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)
            await self._emit_usage()

    # ------------------------------------------------------------- provider

    async def _provider_loop(self) -> None:
        last_error: ProviderStreamError | None = None
        previous_slug: str | None = None
        for attempt in self._attempts:
            replay_idx, offset = self._ring.replay_start() if previous_slug else (0, 0.0)
            adapter = attempt.build()
            try:
                await adapter.connect(attempt.config)
            except ProviderStreamError as exc:
                last_error = exc
                report_provider_failure(
                    exc.provider, attempt.slug, str(exc), code="connect_failed"
                )
                continue
            if previous_slug is not None:
                self._switches += 1
                await self._transport.send_event(
                    ProviderSwitched.model_validate(
                        {
                            "type": "provider_switched",
                            "from": previous_slug,
                            "to": attempt.slug,
                            "resumed_at": round(offset, 3),
                            "speaker_mapping_preserved": False,
                        }
                    )
                )
            previous_slug = attempt.slug
            try:
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._feed(adapter, replay_idx))
                        tg.create_task(self._drain(adapter, offset))
                    return  # clean completion: provider flushed, events exhausted
                except BaseExceptionGroup as group:
                    if group.subgroup(SessionClosed) is not None:
                        raise SessionClosed() from None
                    stream_errors, rest = group.split(ProviderStreamError)
                    if rest is not None or stream_errors is None:
                        raise  # unexpected failure — surface loudly
                    exc = stream_errors.exceptions[0]
                    assert isinstance(exc, ProviderStreamError)
                    if not exc.recoverable:
                        raise exc from None
                    last_error = exc
                    logger.warning(
                        "provider stream failed, trying next",
                        extra={"session": self._session_id, "provider": attempt.slug,
                               "err": str(exc)},
                    )
            finally:
                await adapter.close()
        raise last_error or ProviderStreamError(
            "no providers available", recoverable=False, provider="gateway"
        )

    async def _feed(self, adapter: STTStreamProvider, from_idx: int) -> None:
        async for chunk in self._ring.iter_from(from_idx):
            await adapter.send_audio(chunk.data)
        await adapter.finish()

    async def _drain(self, adapter: STTStreamProvider, offset: float) -> None:
        async for event in adapter.events():
            outgoing = self._normalize(event, offset)
            if outgoing is not None:
                await self._transport.send_event(outgoing)

    def _normalize(self, event, offset: float):
        """Shift adapter-relative times to session time; enforce the failover
        dedup guarantee for finals and endpoint signals."""
        if isinstance(event, Transcript):
            start = None if event.start is None else round(offset + event.start, 3)
            end = None if event.end is None else round(offset + event.end, 3)
            words = None
            if event.words:
                words = [
                    w.model_copy(
                        update={
                            "start": round(offset + w.start, 3),
                            "end": round(offset + w.end, 3),
                        }
                    )
                    for w in event.words
                ]
            if event.is_final and end is not None:
                if end <= self._last_final_end + _EPS:
                    return None  # replayed audio already delivered as final
                self._last_final_end = end
            return event.model_copy(update={"start": start, "end": end, "words": words})
        if isinstance(event, UtteranceEnd):
            at = round(offset + event.at, 3)
            if at <= self._last_utterance_end + _EPS or at <= self._last_final_end - _EPS:
                return None
            self._last_utterance_end = at
            return event.model_copy(update={"at": at})
        if isinstance(event, SpeechStarted):
            at = round(offset + event.at, 3)
            if at <= self._last_final_end + _EPS:
                return None  # replay artifact: speech start inside delivered audio
            return event.model_copy(update={"at": at})
        return event

    # --------------------------------------------------------------- client

    async def _read_client(self) -> None:
        while True:
            message = await self._transport.recv()
            self._last_activity = time.monotonic()
            if message is None:
                await self._ring.close()
                return  # clean disconnect; run() marks client_disconnect
            if isinstance(message, bytes):
                if message and not self._finalized:
                    await self._ring.append(message)
                continue
            event_type = _peek_type(message)
            if event_type == "finalize":
                self._finalized = True
                await self._ring.close()
            elif event_type == "keepalive":
                pass  # activity timestamp already refreshed
            else:
                logger.info(
                    "ignoring unknown client event",
                    extra={"session": self._session_id, "event_type": event_type},
                )

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            if now - self._started > self._settings.max_session_seconds:
                raise SessionLimit(
                    Code.session_expired, "session_expired", "maximum session duration reached"
                )
            if not self._finalized and now - self._last_activity > (
                self._settings.idle_timeout_seconds
            ):
                raise SessionLimit(
                    Code.audio_timeout,
                    "audio_timeout",
                    "no audio or keepalive received; closing idle session",
                )

    # ---------------------------------------------------------------- misc

    async def _try_send_error(self, code: Code, message: str, provider: str | None = None) -> None:
        with contextlib.suppress(SessionClosed):
            await self._transport.send_event(
                Error(type="error", code=code, message=message, provider=provider,
                      recoverable=False)
            )

    async def _emit_usage(self) -> None:
        logger.info(
            "stt session finished",
            extra={
                "session": self._session_id,
                "model": self._attempts[0].slug,
                "audio_seconds": round(self._ring.audio_seconds, 3),
                "status": self._status,
                "provider_switches": self._switches,
                "byok": self._byok,
            },
        )
        with contextlib.suppress(Exception):
            await self._emitter.emit(
                UsageEvent(
                    session_id=self._session_id,
                    key_id=self._key_id,
                    model=self._attempts[0].slug,
                    kind="stt_stream",
                    audio_seconds=round(self._ring.audio_seconds, 3),
                    provider_switches=self._switches,
                    status=self._status,
                    byok=self._byok,
                )
            )


def _peek_type(raw: str) -> str | None:
    import json

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed.get("type") if isinstance(parsed, dict) else None
