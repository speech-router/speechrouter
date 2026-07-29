from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import websockets

from .errors import SpeechRouterError
from .events import Done, ErrorEvent, ListenEvent, SessionOpen, parse_event


class ListenStream:
    """A live transcription session.

    Use as an async context manager and iterate events, or drive it manually
    with send_audio() / finalize() / done().

        async with client.listen(model="deepgram/nova-3") as stream:
            await stream.send_audio(pcm)
            async for event in stream:
                ...
    """

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        connect_timeout: float = 10.0,
        keepalive: float | None = 8.0,
    ):
        self._url = url
        self._api_key = api_key
        self._pending_finalize = False
        self._connect_timeout = connect_timeout
        self._keepalive = keepalive
        self._ws: Any = None
        self._queue: asyncio.Queue[ListenEvent | None] = asyncio.Queue()
        self._pump: asyncio.Task[None] | None = None
        self._ka_task: asyncio.Task[None] | None = None
        self._done: asyncio.Future[Done] = asyncio.get_event_loop().create_future()
        self.session: SessionOpen | None = None
        self.state = "connecting"

    async def __aenter__(self) -> "ListenStream":  # noqa: PYI034, UP037
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        try:
            # Credentials ride Sec-WebSocket-Protocol ("bearer, <key>") so
            # they never appear in URLs, access logs, or proxy traces.
            subprotocols = ["bearer", self._api_key] if self._api_key else None
            self._ws = await asyncio.wait_for(
                websockets.connect(self._url, max_size=2**23, subprotocols=subprotocols),
                self._connect_timeout,
            )
        except TimeoutError as e:
            self._settle_error(SpeechRouterError("connect timed out", code="timeout"))
            raise self._done.exception() from e  # type: ignore[misc]
        except Exception as e:
            err = SpeechRouterError(f"connection failed: {e}", code="connection_failed")
            self._settle_error(err)
            raise err from e
        self.state = "open"
        if self._pending_finalize:
            self.state = "finalizing"
            await self._ws.send(json.dumps({"type": "finalize"}))
        self._pump = asyncio.create_task(self._read_loop())
        if self._keepalive:
            self._ka_task = asyncio.create_task(self._keepalive_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event = parse_event(payload)
                if event is None:
                    continue
                if isinstance(event, SessionOpen):
                    self.session = event
                elif isinstance(event, Done):
                    if not self._done.done():
                        self._done.set_result(event)
                elif isinstance(event, ErrorEvent) and not event.recoverable:
                    self._settle_error(
                        SpeechRouterError(
                            event.message,
                            code=event.code,
                            provider=event.provider,
                            recoverable=False,
                        )
                    )
                await self._queue.put(event)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.state = "closed"
            self._settle_error(
                SpeechRouterError("connection closed before the session finished",
                                  code="connection_closed")
            )
            await self._queue.put(None)

    async def _keepalive_loop(self) -> None:
        assert self._keepalive is not None
        try:
            while True:
                await asyncio.sleep(self._keepalive)
                if self.state == "open":
                    await self._ws.send(json.dumps({"type": "keepalive"}))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    def _settle_error(self, err: SpeechRouterError) -> None:
        if not self._done.done():
            self._done.set_exception(err)

    def __aiter__(self) -> AsyncIterator[ListenEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ListenEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def send_audio(self, chunk: bytes) -> None:
        """Send a chunk of PCM audio."""
        if self.state != "open":
            raise SpeechRouterError(
                f"cannot send audio: stream is {self.state}", code="connection_closed"
            )
        await self._ws.send(chunk)

    async def finalize(self) -> None:
        """Ask the gateway to flush pending audio into a final transcript.
        Queued like audio if the socket hasn't opened yet."""
        if self.state == "open":
            self.state = "finalizing"
            await self._ws.send(json.dumps({"type": "finalize"}))
        elif self.state == "connecting":
            self._pending_finalize = True

    async def done(self) -> Done:
        """Wait for the gateway's usage summary (sent when the session ends)."""
        return await asyncio.shield(self._done)

    async def stop(self, timeout: float = 30.0) -> Done:
        """Graceful shutdown: finalize, await `done`, close. Returns usage."""
        await self.finalize()
        try:
            return await asyncio.wait_for(asyncio.shield(self._done), timeout)
        except TimeoutError as e:
            raise SpeechRouterError("gave up waiting for done", code="timeout") from e
        finally:
            await self.close()

    async def close(self) -> None:
        """Immediate shutdown. Prefer stop() to keep the transcript tail."""
        if self._ka_task:
            self._ka_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001, S110 - already closed is fine
                pass
        if self._pump:
            try:
                await asyncio.wait_for(self._pump, 5)
            except (TimeoutError, asyncio.CancelledError):
                self._pump.cancel()
        self.state = "closed"
