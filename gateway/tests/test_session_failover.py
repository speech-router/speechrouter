"""End-to-end session engine test with scripted fake adapters: proves the
pump loop, ring-buffer replay, provider_switched emission, the final-dedup
guarantee, and exactly-once usage metering."""

import asyncio
import json

from speechrouter_gateway.config import Settings
from speechrouter_gateway.metering import UsageEmitter, UsageEvent
from speechrouter_gateway.protocol import Transcript, UtteranceEnd, Word
from speechrouter_gateway.providers.base import (
    Capabilities,
    ProviderStreamError,
    STTConfig,
    STTStreamProvider,
)
from speechrouter_gateway.router.resolver import ResolvedAttempt
from speechrouter_gateway.router.session import SessionClosed, STTSession

CHUNK = b"\x00" * 16000  # 0.5s at linear16/16k


class FakeTransport:
    """Scripted client: sends frames from a list, then blocks (client waiting)."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent: list[dict] = []
        self._forever = asyncio.Event()

    async def recv(self):
        if self._incoming:
            item = self._incoming.pop(0)
            await asyncio.sleep(0)  # let other tasks interleave
            return item
        await self._forever.wait()  # client idles until session ends

    async def send_event(self, event):
        try:
            self.sent.append(json.loads(event.model_dump_json(by_alias=True, exclude_none=True)))
        except Exception as exc:  # pragma: no cover
            raise SessionClosed() from exc

    def types(self):
        return [e["type"] for e in self.sent]


class CollectingEmitter(UsageEmitter):
    def __init__(self):
        self.events: list[UsageEvent] = []

    async def emit(self, event):
        self.events.append(event)


def _word(w, start, end):
    return Word(w=w, start=start, end=end)


class FlakyAdapter(STTStreamProvider):
    """Receives two chunks, yields interim + final(end=1.0), then dies recoverably."""

    name = "flaky"
    capabilities = Capabilities(streaming=True)

    def __init__(self):
        self.received = 0
        self._got_two = asyncio.Event()

    async def connect(self, config):
        pass

    async def send_audio(self, chunk):
        self.received += 1
        if self.received >= 2:
            self._got_two.set()

    async def events(self):
        await self._got_two.wait()
        yield Transcript(type="transcript", is_final=False, text="hel", start=0.0, end=0.6)
        yield Transcript(
            type="transcript", is_final=True, text="hello",
            words=[_word("hello", 0.2, 0.9)], start=0.0, end=1.0,
        )
        raise ProviderStreamError("upstream died", recoverable=True, provider=self.name)

    async def finish(self):
        pass

    async def close(self):
        pass


class SteadyAdapter(STTStreamProvider):
    """Replacement: re-transcribes replayed audio (duplicate final must be
    suppressed by the session), then emits new content and completes."""

    name = "steady"
    capabilities = Capabilities(streaming=True)

    def __init__(self):
        self.received = 0
        self._finished = asyncio.Event()

    async def connect(self, config):
        pass

    async def send_audio(self, chunk):
        self.received += 1

    async def events(self):
        await self._finished.wait()
        # Replay artifact: covers audio already final at session level -> dropped
        yield Transcript(type="transcript", is_final=True, text="hello", start=0.0, end=1.0)
        # New content past the dedup horizon -> delivered
        yield Transcript(
            type="transcript", is_final=True, text="world",
            words=[_word("world", 1.1, 1.4)], start=1.0, end=1.5,
        )
        yield UtteranceEnd(type="utterance_end", at=1.5)

    async def finish(self):
        self._finished.set()

    async def close(self):
        pass


def _attempt(slug, adapter):
    config = STTConfig(model=slug.split("/")[1], encoding="linear16", sample_rate=16000)
    return ResolvedAttempt(slug=slug, config=config, build=lambda: adapter)


def _settings():
    return Settings(_env_file=None, ring_buffer_seconds=10, idle_timeout_seconds=30)


async def test_failover_replay_dedup_and_usage():
    flaky, steady = FlakyAdapter(), SteadyAdapter()
    transport = FakeTransport([CHUNK, CHUNK, CHUNK, json.dumps({"type": "finalize"})])
    emitter = CollectingEmitter()
    session = STTSession(
        transport=transport,
        attempts=[_attempt("fake/flaky", flaky), _attempt("fake/steady", steady)],
        emitter=emitter,
        key_id="k1",
        settings=_settings(),
    )
    await asyncio.wait_for(session.run(), 5.0)

    types = transport.types()
    assert types[0] == "session.open"
    assert "provider_switched" in types
    assert types[-1] == "done"

    switched = next(e for e in transport.sent if e["type"] == "provider_switched")
    assert switched["from"] == "fake/flaky"
    assert switched["to"] == "fake/steady"
    assert switched["speaker_mapping_preserved"] is False

    finals = [e for e in transport.sent if e["type"] == "transcript" and e["is_final"]]
    # flaky's "hello" delivered once; steady's replayed "hello" suppressed (dedup
    # guarantee); steady's "world" delivered.
    assert [f["text"] for f in finals] == ["hello", "world"]

    # steady received the full replay: all 3 chunks went to both adapters
    assert flaky.received >= 2
    assert steady.received == 3

    done = transport.sent[-1]
    assert done["usage"]["audio_seconds"] == 1.5  # 3 x 0.5s chunks

    assert len(emitter.events) == 1
    usage = emitter.events[0]
    assert usage.status == "completed"
    assert usage.provider_switches == 1
    assert usage.audio_seconds == 1.5
    assert usage.model == "fake/flaky"


async def test_unrecoverable_error_fails_fast_with_usage():
    class FatalAdapter(FlakyAdapter):
        name = "fatal"

        async def events(self):
            await self._got_two.wait()
            raise ProviderStreamError("bad audio config", recoverable=False, provider=self.name)
            yield  # pragma: no cover

    fatal = FatalAdapter()
    transport = FakeTransport([CHUNK, CHUNK])
    emitter = CollectingEmitter()
    session = STTSession(
        transport=transport,
        attempts=[_attempt("fake/fatal", fatal), _attempt("fake/steady", SteadyAdapter())],
        emitter=emitter,
        key_id="k1",
        settings=_settings(),
    )
    await asyncio.wait_for(session.run(), 5.0)

    error = transport.sent[-1]
    assert error["type"] == "error"
    assert error["code"] == "provider_error"
    assert error["recoverable"] is False
    assert len(emitter.events) == 1
    assert emitter.events[0].status == "provider_error"


async def test_client_disconnect_still_meters_usage():
    class QuietAdapter(SteadyAdapter):
        name = "quiet"

    transport = FakeTransport([CHUNK, None])  # one chunk then disconnect
    emitter = CollectingEmitter()
    session = STTSession(
        transport=transport,
        attempts=[_attempt("fake/quiet", QuietAdapter())],
        emitter=emitter,
        key_id="k1",
        settings=_settings(),
    )
    await asyncio.wait_for(session.run(), 5.0)
    assert len(emitter.events) == 1
    assert emitter.events[0].audio_seconds == 0.5
