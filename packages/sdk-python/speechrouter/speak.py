from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import websockets

from .errors import SpeechRouterError
from .events import AudioChunk, Done, ErrorEvent, ListenEvent, SessionOpen, parse_event


class SpeakStream:
    """A streaming text-to-speech session on WSS /v1/speak.

    Send text as it arrives (e.g. LLM tokens); iterate to receive audio.
    Each AudioChunk carries its binary frame in `.data`.

        async with client.speak(model="openai/gpt-4o-mini-tts", voice="marin") as tts:
            for token in llm_tokens:
                await tts.send_text(token)
            await tts.finalize()
            async for event in tts:
                if isinstance(event, AudioChunk):
                    play(event.data)
    """

    def __init__(self, url: str, *, api_key: str | None = None, connect_timeout: float = 10.0):
        self._url = url
        self._api_key = api_key
        self._connect_timeout = connect_timeout
        self._ws: Any = None
        self._queue: asyncio.Queue[ListenEvent | None] = asyncio.Queue()
        self._pump: asyncio.Task[None] | None = None
        self._done: asyncio.Future[Done] = asyncio.get_event_loop().create_future()
        self.session: SessionOpen | None = None
        self.state = "connecting"

    async def __aenter__(self) -> "SpeakStream":  # noqa: PYI034, UP037
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        subprotocols = ["bearer", self._api_key] if self._api_key else None
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self._url, max_size=2**23, subprotocols=subprotocols),
                self._connect_timeout,
            )
        except TimeoutError as e:
            raise SpeechRouterError("connect timed out", code="timeout") from e
        except Exception as e:
            raise SpeechRouterError(f"connection failed: {e}", code="connection_failed") from e
        self.state = "open"
        self._pump = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        pending: AudioChunk | None = None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    if pending is not None:
                        pending.data = raw
                        await self._queue.put(pending)
                        pending = None
                    continue
                try:
                    event = parse_event(json.loads(raw))
                except json.JSONDecodeError:
                    continue
                if event is None:
                    continue
                if isinstance(event, AudioChunk):
                    pending = event  # its audio is the next binary frame
                    continue
                if isinstance(event, SessionOpen):
                    self.session = event
                elif isinstance(event, Done) and not self._done.done():
                    self._done.set_result(event)
                elif isinstance(event, ErrorEvent) and not self._done.done():
                    self._done.set_exception(SpeechRouterError(
                        event.message, code=event.code, provider=event.provider))
                await self._queue.put(event)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.state = "closed"
            if not self._done.done():
                self._done.set_exception(SpeechRouterError(
                    "connection closed before the session finished", code="connection_closed"))
            await self._queue.put(None)

    def __aiter__(self) -> AsyncIterator[ListenEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[ListenEvent]:
        while True:
            event = await self._queue.get()
            if event is None or isinstance(event, Done):
                if event is not None:
                    yield event
                return
            yield event

    async def _send(self, payload: dict[str, Any]) -> None:
        if self.state != "open":
            raise SpeechRouterError(f"cannot send: stream is {self.state}",
                                    code="connection_closed")
        await self._ws.send(json.dumps(payload))

    async def send_text(self, text: str) -> None:
        """Append text to speak. Fragments are fine; the gateway segments."""
        await self._send({"type": "text.delta", "text": text})

    async def clear(self) -> None:
        """Barge-in: drop queued and in-flight audio. A `Cleared` event follows."""
        await self._send({"type": "clear"})

    async def finalize(self) -> None:
        """No more text: the rest is spoken, then `Done` arrives."""
        await self._send({"type": "finalize"})
        self.state = "finalizing"

    async def done(self) -> Done:
        return await asyncio.shield(self._done)

    async def close(self) -> None:
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
