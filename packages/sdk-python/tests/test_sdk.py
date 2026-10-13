import asyncio
import json

import pytest
import websockets

from speechrouter import Done, SpeechRouter, SpeechRouterError, Transcript
from speechrouter.events import parse_event


@pytest.fixture
async def ws_server():
    """One-shot mock gateway: captures the path, scripts the responses."""
    state = {"path": None, "received": [], "script": None}

    async def handler(conn):
        state["path"] = conn.request.path
        if state["script"]:
            await state["script"](conn, state)
        else:
            async for msg in conn:
                state["received"].append(msg)

    server = await websockets.serve(handler, "127.0.0.1", 0)
    state["port"] = server.sockets[0].getsockname()[1]
    yield state
    server.close()
    await server.wait_closed()


def client(port):
    return SpeechRouter(api_key="sk_sr_test", base_url=f"http://127.0.0.1:{port}")


async def test_listen_full_session(ws_server):
    async def script(conn, state):
        await conn.send(json.dumps({"type": "session.open", "session_id": "s1", "model": "deepgram/nova-3"}))
        async for msg in conn:
            if isinstance(msg, bytes):
                state["received"].append(msg)
            elif json.loads(msg).get("type") == "finalize":
                await conn.send(json.dumps({"type": "transcript", "is_final": True, "text": "never lose a word",
                                            "words": [{"w": "never", "start": 0.0, "end": 0.3}]}))
                await conn.send(json.dumps({"type": "done", "usage": {"audio_seconds": 1.5}}))
                await conn.close()
                return

    ws_server["script"] = script
    finals = []
    async with client(ws_server["port"]).listen(
        model="deepgram/nova-3", fallbacks=["soniox/stt-rt-v5"], keepalive=None
    ) as stream:
        await stream.send_audio(b"\x00\x01" * 100)
        await stream.finalize()
        async for event in stream:
            if isinstance(event, Transcript) and event.is_final:
                finals.append(event)
        done = await stream.done()

    assert isinstance(done, Done) and done.usage["audio_seconds"] == 1.5
    assert finals[0].text == "never lose a word"
    assert finals[0].words[0].w == "never"
    assert stream.session.session_id == "s1"
    assert "fallbacks=soniox%2Fstt-rt-v5" in ws_server["path"]
    assert b"\x00\x01" * 100 in ws_server["received"]


async def test_listen_error_event_rejects_done(ws_server):
    async def script(conn, state):
        await conn.send(json.dumps({"type": "error", "code": "concurrency_exceeded",
                                    "message": "limit reached", "recoverable": False}))
        await conn.close()

    ws_server["script"] = script
    async with client(ws_server["port"]).listen(model="deepgram/nova-3", keepalive=None) as stream:
        with pytest.raises(SpeechRouterError) as exc:
            await stream.done()
    assert exc.value.code == "concurrency_exceeded"


async def test_connection_refused():
    sr = SpeechRouter(api_key="k", base_url="http://127.0.0.1:1")
    stream = sr.listen(model="deepgram/nova-3", keepalive=None)
    with pytest.raises(SpeechRouterError) as exc:
        await stream.connect()
    assert exc.value.code == "connection_failed"


async def test_keepalive_frames(ws_server):
    async def script(conn, state):
        await conn.send(json.dumps({"type": "session.open", "session_id": "s", "model": "m"}))
        async for msg in conn:
            state["received"].append(msg)

    ws_server["script"] = script
    async with client(ws_server["port"]).listen(model="m", keepalive=0.03):
        await asyncio.sleep(0.11)
    kept = [m for m in ws_server["received"]
            if isinstance(m, str) and json.loads(m).get("type") == "keepalive"]
    assert len(kept) >= 2


def test_parse_event_maps_from_and_ignores_unknown():
    ev = parse_event({"type": "provider_switched", "from": "a/x", "to": "b/y",
                      "resumed_at": 1.0, "speaker_mapping_preserved": False})
    assert ev.from_ == "a/x" and ev.to == "b/y"
    assert parse_event({"type": "brand.new.event"}) is None


async def test_transcribe_and_errors(monkeypatch):
    import httpx

    calls = {}

    async def fake_request(self, method, url, **kwargs):
        calls["url"] = url
        calls["data"] = kwargs.get("data")
        calls["files"] = kwargs.get("files")
        if "fail" in calls["data"]["model"]:
            return httpx.Response(404, json={"error": {"code": "model_not_found", "message": "nope"}},
                                  request=httpx.Request(method, url))
        return httpx.Response(200, json={"text": "hi"}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    sr = SpeechRouter(api_key="k", base_url="https://gw.test")
    result = await sr.transcribe(model="deepgram/nova-3", file=b"audio-bytes", diarization=True)
    assert result == {"text": "hi"}
    assert calls["url"] == "https://gw.test/v1/audio/transcriptions"
    assert calls["data"]["diarization"] == "true"
    assert calls["files"]["file"][0] == "audio"

    with pytest.raises(SpeechRouterError) as exc:
        await sr.transcribe(model="fail/x", file=b"z")
    assert exc.value.code == "model_not_found" and exc.value.status == 404

    with pytest.raises(SpeechRouterError):
        await sr.transcribe(model="deepgram/nova-3")  # no file, no url


async def test_create_token(monkeypatch):
    import httpx

    async def fake_request(self, method, url, **kwargs):
        assert url.endswith("/v1/tokens") and kwargs["json"] == {"ttl_seconds": 90}
        return httpx.Response(200, json={"token": "st_x", "ttl_seconds": 90},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    sr = SpeechRouter(api_key="k", base_url="https://gw.test")
    out = await sr.create_token(ttl_seconds=90)
    assert out["token"] == "st_x"


# ---- TTS: speak (WS) + speech (REST) ----

async def test_speak_pairs_chunk_metadata_with_audio(ws_server):
    from speechrouter import AudioChunk, Cleared

    async def script(conn, state):
        await conn.send(json.dumps({"type": "session.open", "session_id": "speak_1",
                                    "model": "openai/gpt-4o-mini-tts", "voice": "marin"}))
        async for msg in conn:
            event = json.loads(msg)
            state["received"].append(event)
            if event["type"] == "clear":
                await conn.send(json.dumps({"type": "cleared", "last_seq": 1}))
            if event["type"] == "finalize":
                for seq, data in ((1, b"\x01\x02"), (2, b"\x03\x04")):
                    await conn.send(json.dumps({"type": "audio.chunk", "seq": seq, "start": 0.0}))
                    await conn.send(data)
                await conn.send(json.dumps({"type": "done", "usage": {"characters": 5}}))

    ws_server["script"] = script
    sr = client(ws_server["port"])
    async with sr.speak(model="openai/gpt-4o-mini-tts", voice="marin") as tts:
        await tts.send_text("Hello")
        await tts.clear()
        await tts.finalize()
        events = [e async for e in tts]
        assert tts.session is not None and tts.session.voice == "marin"
        assert (await tts.done()).usage == {"characters": 5}
    chunks = [e for e in events if isinstance(e, AudioChunk)]
    assert [(c.seq, c.data) for c in chunks] == [(1, b"\x01\x02"), (2, b"\x03\x04")]
    assert any(isinstance(e, Cleared) for e in events)
    assert "/v1/speak?model=openai%2Fgpt-4o-mini-tts" in ws_server["path"]
    assert "voice=marin" in ws_server["path"] and "encoding=linear16" in ws_server["path"]
    assert [e["type"] for e in ws_server["received"]] == ["text.delta", "clear", "finalize"]


@pytest.fixture
def speech_transport(monkeypatch):
    import httpx

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        if seen["body"]["model"] == "nope/x":
            return httpx.Response(404, json={"error": {"code": "model_not_found",
                                                       "message": "no such model"}})
        return httpx.Response(200, content=b"AUDIO" * 100)

    real = httpx.AsyncClient
    monkeypatch.setattr("speechrouter.client.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


async def test_speech_returns_bytes_and_streams(speech_transport):
    sr = SpeechRouter(api_key="sk_sr_test", base_url="http://gw")
    audio = await sr.speech(model="openai/tts-1", input="hi", voice="alloy", speed=1.5)
    assert audio == b"AUDIO" * 100
    assert speech_transport["body"] == {"model": "openai/tts-1", "input": "hi", "voice": "alloy",
                                        "speed": 1.5, "stream": False}
    assert speech_transport["auth"] == "Bearer sk_sr_test"
    streamed = b"".join([c async for c in sr.speech_stream(model="openai/tts-1", input="hi")])
    assert streamed == b"AUDIO" * 100 and "stream" not in speech_transport["body"]


async def test_speech_errors_raise_typed(speech_transport):
    sr = SpeechRouter(api_key="sk_sr_test", base_url="http://gw")
    with pytest.raises(SpeechRouterError) as info:
        await sr.speech(model="nope/x", input="hi")
    assert info.value.code == "model_not_found"
    with pytest.raises(SpeechRouterError) as info:
        async for _ in sr.speech_stream(model="nope/x", input="hi"):
            pass
    assert info.value.code == "model_not_found"
