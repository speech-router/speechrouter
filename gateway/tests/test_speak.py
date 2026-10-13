"""WSS /v1/speak: segmenter, session pipeline (order, prefetch, barge-in,
finalize, usage), and the endpoint over a real Starlette websocket."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from speechrouter_gateway.config import Settings
from speechrouter_gateway.providers import registry
from speechrouter_gateway.providers.base import TTSCapabilities, TTSProvider
from speechrouter_gateway.router.catalog import Catalog
from speechrouter_gateway.router.resolver import TTSRequest, resolve_tts
from speechrouter_gateway.tts.segmenter import TextSegmenter
from speechrouter_gateway.tts.session import SpeakSession

# ------------------------------------------------------------- segmenter


def test_segmenter_cuts_on_sentence_ends_and_merges_short_ones():
    seg = TextSegmenter(min_chars=20)
    assert seg.push("Hi. ") == []  # too short alone
    assert seg.push("How are you doing today? I am") == ["Hi. How are you doing today?"]
    assert seg.pending == "I am"
    assert seg.push(" fine.\nNext") == []  # still under min_chars: merges forward
    assert seg.push(" up is the weather report.\n") == [
        "I am fine.\nNext up is the weather report."
    ]
    assert seg.flush() is None


def test_segmenter_does_not_cut_decimals_and_handles_cjk():
    seg = TextSegmenter(min_chars=5)
    assert seg.push("Version 3.5 is out") == []
    assert seg.push("こんにちは世界。元気ですか") == ["Version 3.5 is outこんにちは世界。"]


def test_segmenter_forces_cut_at_max_chars_on_word_boundary():
    seg = TextSegmenter(min_chars=5, max_chars=20)
    out = seg.push("alpha beta gamma delta epsilon zeta")
    assert out and all(len(s) <= 20 for s in out)
    assert " ".join(out + [seg.flush() or ""]).split() == \
        "alpha beta gamma delta epsilon zeta".split()


def test_segmenter_take_stale_cuts_at_last_word():
    seg = TextSegmenter(min_chars=10)
    seg.push("the quick brown fox jum")
    assert seg.take_stale() == "the quick brown fox"
    assert seg.pending == "jum"
    assert seg.take_stale() is None


# ------------------------------------------------------------- fakes

CHUNK = b"\x10\x00" * 240  # 10 ms of 24 kHz pcm


class FakeTTS(TTSProvider):
    """Yields 3 chunks per segment. `gates[text]` (an Event) holds the
    stream after the first chunk so a test can barge in mid-segment."""

    name = "faketts"
    capabilities = TTSCapabilities(formats=frozenset({"pcm"}),
                                   sample_rates=frozenset({24000}), default_voice="v")
    gates: dict[str, asyncio.Event] = {}
    started: list[str] = []
    fail_on: str | None = None

    async def synthesize(self, text, config, usage):
        FakeTTS.started.append(text)
        usage.characters += len(text)
        if text == FakeTTS.fail_on:
            from speechrouter_gateway.providers.base import ProviderStreamError
            raise ProviderStreamError("vendor exploded: account 42 overdrawn",
                                      recoverable=False, provider="faketts", code="upstream_5xx")
        yield CHUNK
        gate = FakeTTS.gates.get(text)
        if gate is not None:
            await gate.wait()
        yield CHUNK
        yield CHUNK
        usage.tokens["audio_output_tokens"] = 30.0


ENTRY = {"slug": "faketts/m", "provider": "faketts", "kind": "tts",
         "modes": ["streaming"], "pricing": {"per_1m_audio_output_tokens_usd": 10.0},
         "capabilities": {"formats": ["pcm", "mulaw"], "output_sample_rates": [24000, 8000],
                          "voices": ["v"], "default_voice": "v"}}


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch):
    FakeTTS.gates = {}
    FakeTTS.started = []
    FakeTTS.fail_on = None
    monkeypatch.setitem(registry._tts, "faketts",
                        registry.RegisteredTTS(lambda s: FakeTTS(), FakeTTS.capabilities))


class FakeTransport:
    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list = []  # ("event", dict) | ("audio", bytes)

    async def recv(self):
        return await self.inbox.get()

    async def send_event(self, event):
        self.sent.append(("event", json.loads(event.model_dump_json(exclude_none=True))))

    async def send_audio(self, data):
        self.sent.append(("audio", data))

    def say(self, **event):
        self.inbox.put_nowait(json.dumps(event))

    def events(self, kind=None):
        return [e for t, e in self.sent if t == "event" and (kind is None or e["type"] == kind)]


class CaptureEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def _session(transport, fmt="pcm", **settings_kw):
    settings = Settings(_env_file=None, **settings_kw)
    resolved = resolve_tts("faketts/m", TTSRequest(format=fmt), settings, Catalog([ENTRY]))
    emitter = CaptureEmitter()
    return SpeakSession(transport, resolved, emitter, "key1", settings), emitter


async def _until(predicate, limit=2.0):
    """Poll a condition on the session's observable output."""
    async with asyncio.timeout(limit):
        while not predicate():  # noqa: ASYNC110 - observing a black box, no event to await
            await asyncio.sleep(0.005)


# ------------------------------------------------------------- session


async def test_session_streams_segments_in_order_then_done():
    transport = FakeTransport()
    session, emitter = _session(transport)
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text="The first sentence is here. ")
    transport.say(type="text.delta", text="And then a second one arrives.")
    transport.say(type="finalize")
    await asyncio.wait_for(task, 2)

    kinds = [t if t == "audio" else e["type"] for t, e in transport.sent]
    assert kinds[0] == "session.open" and kinds[-1] == "done"
    body = kinds[1:-1]
    assert body == ["audio.chunk", "audio"] * 6  # 2 segments x 3 chunks, strictly paired
    chunks = transport.events("audio.chunk")
    assert [c["seq"] for c in chunks] == list(range(1, 7))
    assert chunks[1]["start"] == 0.01 and chunks[5]["start"] == 0.05  # sent-audio clock
    assert FakeTTS.started == ["The first sentence is here.", "And then a second one arrives."]

    done = transport.events("done")[0]["usage"]
    assert done["characters"] == 27 + 30 and done["units"] == {"audio_output_tokens": 60.0}
    (event,) = emitter.events
    assert event.kind == "tts_stream" and event.status == "completed"
    assert event.session_id.startswith("speak_") and event.audio_seconds == 0.06
    assert event.units == {"audio_output_tokens": 60.0}
    assert abs(event.list_cost_usd - 60 * 10.0 / 1e6) < 1e-12


async def test_prefetch_starts_next_segment_while_current_is_sending():
    transport = FakeTransport()
    session, _ = _session(transport)
    FakeTTS.gates["Segment number one, held open."] = asyncio.Event()
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text="Segment number one, held open. Segment two follows. ")
    await _until(lambda: len(FakeTTS.started) == 2)  # #2 started while #1 is blocked
    assert len(transport.events("audio.chunk")) == 1
    FakeTTS.gates["Segment number one, held open."].set()
    transport.say(type="finalize")
    await asyncio.wait_for(task, 2)
    assert len(transport.events("audio.chunk")) == 6


async def test_clear_drops_queued_audio_acks_last_seq_and_keeps_going():
    transport = FakeTransport()
    session, emitter = _session(transport)
    held = "This one gets interrupted midway."
    FakeTTS.gates[held] = asyncio.Event()
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text=f"{held} This queued one is dropped too. ")
    await _until(lambda: len(transport.events("audio.chunk")) == 1)
    transport.say(type="clear")
    await _until(lambda: transport.events("cleared"))
    assert transport.events("cleared")[0]["last_seq"] == 1

    transport.say(type="text.delta", text="Fresh text after the barge-in.")
    transport.say(type="finalize")
    await asyncio.wait_for(task, 2)
    after = transport.sent[transport.sent.index(("event", transport.events("cleared")[0])):]
    assert len([1 for t, _ in after if t == "audio"]) == 3  # only post-clear synthesis
    assert [c["seq"] for c in transport.events("audio.chunk")][-3:] == [2, 3, 4]
    (event,) = emitter.events
    # interrupted + prefetched segments were generated upstream: still metered
    assert event.characters == len(held) + len("This queued one is dropped too.") + 30
    assert event.status == "completed"


async def test_provider_error_reaches_client_sanitized_and_is_metered():
    transport = FakeTransport()
    session, emitter = _session(transport)
    FakeTTS.fail_on = "This sentence makes the vendor fail."
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text=FakeTTS.fail_on)
    transport.say(type="finalize")
    await asyncio.wait_for(task, 2)
    (error,) = transport.events("error")
    assert error["code"] == "provider_error" and "overdrawn" not in error["message"]
    assert emitter.events[0].status == "provider_error"
    assert emitter.events[0].units == {}  # nothing generated -> nothing billed


async def test_client_disconnect_is_metered_once():
    transport = FakeTransport()
    session, emitter = _session(transport)
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text="Some words that will be spoken now. ")
    await _until(lambda: len(transport.events("audio.chunk")) == 3)
    transport.inbox.put_nowait(None)
    await asyncio.wait_for(task, 2)
    (event,) = emitter.events
    assert event.status == "client_disconnect" and event.characters > 0


async def test_idle_session_times_out(monkeypatch):
    transport = FakeTransport()
    session, emitter = _session(transport, idle_timeout_seconds=0)
    await asyncio.wait_for(session.run(), 2)
    assert transport.events("error")[0]["code"] == "audio_timeout"
    assert emitter.events[0].status == "audio_timeout"


async def test_stale_clause_is_spoken_without_waiting_for_a_period():
    transport = FakeTransport()
    session, _ = _session(transport)
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text="an unpunctuated clause from a slow model")
    await _until(lambda: FakeTTS.started)
    assert FakeTTS.started == ["an unpunctuated clause from a slow"]
    transport.say(type="finalize")
    await asyncio.wait_for(task, 2)
    assert FakeTTS.started[-1] == "model"


async def test_mulaw_output_is_decimated_and_clock_counts_bytes():
    transport = FakeTransport()
    session, _ = _session(transport, fmt="mulaw")
    task = asyncio.create_task(session.run())
    transport.say(type="text.delta", text="Telephone audio please, thanks.")
    transport.say(type="finalize")
    await asyncio.wait_for(task, 2)
    opened = transport.events("session.open")[0]
    assert opened["encoding"] == "mulaw" and opened["sample_rate"] == 8000
    audio = b"".join(d for t, d in transport.sent if t == "audio")
    assert len(audio) == 3 * 80  # 3 x 10 ms at 8 kHz, 1 byte/sample


# ------------------------------------------------------------- endpoint


@pytest.fixture()
def app_client():
    from speechrouter_gateway.auth import build_keystore
    from speechrouter_gateway.config import KeyStoreKind
    from speechrouter_gateway.main import app

    with TestClient(app) as client:
        app.state.settings = app.state.settings.model_copy(
            update={"keys": "sk_test", "keystore": KeyStoreKind.local})
        app.state.keystore = build_keystore(app.state.settings)
        app.state.catalog = Catalog([ENTRY])
        app.state.emitter = CaptureEmitter()
        yield client, app


def test_endpoint_roundtrip_with_subprotocol_auth(app_client):
    client, app = app_client
    with client.websocket_connect("/v1/speak?model=faketts/m&encoding=linear16",
                                  subprotocols=["bearer", "sk_test"]) as ws:
        opened = json.loads(ws.receive_text())
        assert opened["type"] == "session.open" and opened["voice"] == "v"
        ws.send_text(json.dumps({"type": "text.delta", "text": "Hello from the socket test."}))
        ws.send_text(json.dumps({"type": "finalize"}))
        frames = []
        while True:
            message = ws.receive()
            if message.get("text") and json.loads(message["text"])["type"] == "done":
                break
            frames.append("text" if message.get("text") else "bytes")
        assert frames == ["text", "bytes"] * 3
    assert app.state.emitter.events[0].kind == "tts_stream"


def test_endpoint_rejects_bad_auth_model_and_encoding(app_client):
    client, _ = app_client
    for url, code in [
        ("/v1/speak?model=faketts/m", "auth_failed"),
        ("/v1/speak?model=faketts/m&api_key=sk_test&encoding=wav", "invalid_request"),
        ("/v1/speak?model=nope/x&api_key=sk_test", "model_not_found"),
        ("/v1/speak?api_key=sk_test", "invalid_request"),
    ]:
        with client.websocket_connect(url) as ws:
            assert json.loads(ws.receive_text())["code"] == code, url
