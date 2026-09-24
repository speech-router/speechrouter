"""xAI Grok Voice Transcribe fixtures. Frames are the documented examples in
docs.x.ai (speech-to-text guide, stt-streaming.ws.json, REST reference);
the stitching cases cover both readings of the undocumented chunk semantics
(docs/providers/xai.md, Open 3/4)."""

import asyncio
import json
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from speechrouter_gateway.protocol import Transcript, UtteranceEnd
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.xai import adapter as mod
from speechrouter_gateway.providers.xai.adapter import (
    UtteranceState,
    XAISTTStream,
    build_url,
    parse_message,
)
from speechrouter_gateway.providers.xai.batch import XAIBatch, build_form, parse_response


def _config(**kwargs) -> STTConfig:
    base = {"model": "grok-voice-transcribe-2.0", "encoding": "linear16", "sample_rate": 16000}
    base.update(kwargs)
    return STTConfig(**base)


def _query(url: str) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(url).query)


def _partial(text, start, duration, *, is_final, speech_final=False, words=()):
    return json.dumps({
        "type": "transcript.partial", "text": text, "words": list(words),
        "is_final": is_final, "speech_final": speech_final,
        "start": start, "duration": duration,
    })


def _w(text, start, end, **extra):
    return {"text": text, "start": start, "end": end, **extra}


def _run(frames, state=None):
    state = state or UtteranceState()
    events = []
    for frame in frames:
        events.extend(parse_message(frame, state))
    return events, state


def _transcripts(events):
    return [e for e in events if isinstance(e, Transcript)]


# ------------------------------------------------------------------- url


def test_url_carries_config_as_query_params():
    q = _query(build_url(_config(
        language="en-US", diarization=True, keyterms=("Understand The Universe", "Grok"),
    )))
    assert q == [
        ("model", "grok-voice-transcribe-2.0"),
        ("encoding", "pcm"),
        ("sample_rate", "16000"),
        ("interim_results", "true"),
        ("language", "en"),  # bare code; it only switches on ITN
        ("diarize", "true"),
        ("keyterm", "Understand The Universe"),  # repeated, one per term
        ("keyterm", "Grok"),
    ]


def test_url_maps_telephony_audio_and_omits_auto():
    q = dict(_query(build_url(_config(encoding="mulaw", sample_rate=8000, language="auto",
                                      interim_results=False))))
    assert q["encoding"] == "mulaw" and q["sample_rate"] == "8000"
    assert q["interim_results"] == "false"
    assert "language" not in q  # the STT API does not accept `auto`


def test_url_provider_params_lowercase_bools_and_keep_reserved_keys():
    q = _query(build_url(_config(provider_params={
        "smart_turn": 0.7, "filler_words": True, "encoding": "opus", "model": "x",
    })))
    assert ("smart_turn", "0.7") in q
    assert ("filler_words", "true") in q
    assert dict(q)["encoding"] == "pcm" and dict(q)["model"] == "grok-voice-transcribe-2.0"


@pytest.mark.parametrize("kwargs", [
    {"model": "grok-voice-transcribe-2.0-batch"},  # batch slug, batch price
    {"encoding": "opus"},  # one packet per frame cannot survive ring replay
    {"channels": 2},
    {"sample_rate": 11025},
])
def test_url_refuses_what_the_socket_cannot_carry(kwargs):
    with pytest.raises(ProviderStreamError) as exc:
        build_url(_config(**kwargs))
    assert exc.value.recoverable is False


# --------------------------------------------------------------- events


def test_documented_chunk_final_is_an_interim_with_word_confidence():
    frame = json.dumps({
        "type": "transcript.partial", "text": "The balance is $167,983.15.",
        "words": [
            {"text": "The", "start": 0.24, "end": 0.48, "confidence": 0.95},
            {"text": "balance", "start": 0.48, "end": 0.96, "confidence": 0.92},
            {"text": "is", "start": 0.96, "end": 1.12, "confidence": 0.98},
            {"text": "$167,983.15.", "start": 1.12, "end": 3.2, "confidence": 0.89},
        ],
        "is_final": True, "speech_final": False, "start": 0.0, "duration": 3.2,
    })
    events, _ = _run([frame])
    (t,) = events
    assert isinstance(t, Transcript) and t.is_final is False  # locked, not ended
    assert t.text == "The balance is $167,983.15."
    assert t.start == 0.0 and t.end == 3.2
    assert t.words[0].conf == 0.95 and t.words[3].w == "$167,983.15."


def test_documented_smart_turn_utterance_final():
    frame = json.dumps({
        "type": "transcript.partial", "text": "I will buy two of those, please.",
        "words": [], "is_final": True, "speech_final": True, "start": 0.0,
        "duration": 2.4, "end_of_turn_confidence": 0.983,
    })
    events, state = _run([frame])
    t, end = events
    assert t.is_final is True and t.text == "I will buy two of those, please."
    assert t.end == 2.4
    assert isinstance(end, UtteranceEnd) and end.at == 2.4
    assert state.final_end == 2.4


def test_cumulative_speech_final_is_not_doubled():
    """Reading 1: speech_final is the complete stitched utterance."""
    events, _ = _run([
        _partial("One two three.", 0.0, 3.0, is_final=True,
                 words=[_w("One", 0.1, 0.5), _w("two", 0.6, 1.0), _w("three.", 1.1, 2.9)]),
        _partial("One two three. Four five.", 0.0, 5.0, is_final=True, speech_final=True,
                 words=[_w("One", 0.1, 0.5), _w("two", 0.6, 1.0), _w("three.", 1.1, 2.9),
                        _w("Four", 3.1, 3.6), _w("five.", 3.7, 4.8)]),
    ])
    finals = [t for t in _transcripts(events) if t.is_final]
    assert [t.text for t in finals] == ["One two three. Four five."]
    assert len(finals[0].words) == 5 and finals[0].start == 0.0 and finals[0].end == 5.0


def test_tail_only_events_are_stitched_onto_the_locked_text():
    """Reading 2: each event carries only the audio after the locked chunk."""
    events, _ = _run([
        _partial("One two three.", 0.0, 3.0, is_final=True,
                 words=[_w("One", 0.1, 0.5), _w("two", 0.6, 1.0), _w("three.", 1.1, 2.9)]),
        _partial("Four", 3.0, 0.8, is_final=False, words=[_w("Four", 3.1, 3.6)]),
        _partial("Four five.", 3.0, 2.0, is_final=True, speech_final=True,
                 words=[_w("Four", 3.1, 3.6), _w("five.", 3.7, 4.8)]),
    ])
    interim = _transcripts(events)[1]
    assert interim.is_final is False and interim.text == "One two three. Four"
    final = _transcripts(events)[-1]
    assert final.is_final is True and final.text == "One two three. Four five."
    assert [w.w for w in final.words] == ["One", "two", "three.", "Four", "five."]
    assert final.start == 0.0 and final.end == 5.0


def test_empty_speech_final_still_releases_the_locked_text():
    events, _ = _run([
        _partial("Hello there.", 0.0, 2.0, is_final=True),
        _partial("", 0.0, 2.4, is_final=True, speech_final=True),
    ])
    finals = [t for t in _transcripts(events) if t.is_final]
    assert [t.text for t in finals] == ["Hello there."]


def test_utterances_reset_between_speech_finals():
    events, _ = _run([
        _partial("First.", 0.0, 1.0, is_final=True, speech_final=True),
        _partial("Second.", 2.0, 1.0, is_final=True, speech_final=True),
    ])
    finals = [t for t in _transcripts(events) if t.is_final]
    assert [(t.text, t.start, t.end) for t in finals] == [("First.", 0.0, 1.0),
                                                            ("Second.", 2.0, 3.0)]


def test_relative_word_times_are_shifted_to_stream_time():
    # Absolute words cannot precede their event; these must be event-relative.
    events, _ = _run([_partial("Later.", 10.0, 1.0, is_final=True, speech_final=True,
                               words=[_w("Later.", 0.2, 0.9)])])
    word = _transcripts(events)[0].words[0]
    assert (word.start, word.end) == (10.2, 10.9)


def test_diarized_words_keep_speaker_indices():
    events, _ = _run([_partial("Hi. Yo.", 0.0, 2.0, is_final=True, speech_final=True,
                               words=[_w("Hi.", 0.1, 0.4, speaker=0),
                                      _w("Yo.", 1.0, 1.3, speaker=1)])])
    assert [w.speaker for w in _transcripts(events)[0].words] == [0, 1]


def test_documented_done_with_nothing_pending_emits_nothing():
    events, state = _run([
        _partial("Done.", 0.0, 1.0, is_final=True, speech_final=True),
        json.dumps({"type": "transcript.done", "text": "", "words": [], "duration": 6.43}),
    ])
    assert [t.text for t in _transcripts(events)] == ["Done."]
    assert state.done is True


def test_done_as_full_transcript_only_surfaces_the_unfinalized_tail():
    events, _ = _run([
        _partial("One.", 0.0, 1.0, is_final=True, speech_final=True,
                 words=[_w("One.", 0.1, 0.8)]),
        json.dumps({"type": "transcript.done", "text": "One. Two.", "duration": 3.0,
                    "words": [_w("One.", 0.1, 0.8), _w("Two.", 2.0, 2.6)]}),
    ])
    finals = [t for t in _transcripts(events) if t.is_final]
    assert [t.text for t in finals] == ["One.", "Two."]
    assert finals[1].start == 2.0 and finals[1].end == 2.6


def test_done_flushes_a_pending_chunk_final():
    events, _ = _run([
        _partial("Cut off mid", 0.0, 2.0, is_final=True, words=[_w("Cut", 0.1, 0.4),
                                                               _w("off", 0.5, 0.8),
                                                               _w("mid", 0.9, 1.9)]),
        json.dumps({"type": "transcript.done", "text": "Cut off mid", "duration": 2.0,
                    "words": [_w("Cut", 0.1, 0.4), _w("off", 0.5, 0.8), _w("mid", 0.9, 1.9)]}),
    ])
    finals = [t for t in _transcripts(events) if t.is_final]
    assert [t.text for t in finals] == ["Cut off mid"]
    assert len(finals[0].words) == 3


def test_done_text_without_words_is_used_when_nothing_was_final():
    events, _ = _run([json.dumps({"type": "transcript.done", "text": "Only this.",
                                  "words": [], "duration": 1.5})])
    (t,) = _transcripts(events)
    assert t.is_final is True and t.text == "Only this." and t.end == 1.5


def test_error_frame_is_recorded_and_unknown_frames_ignored():
    events, state = _run([
        json.dumps({"type": "error",
                    "message": "Invalid message: expected {\"type\": \"audio.done\"}"}),
        json.dumps({"type": "transcript.created", "id": "83f2f6fd"}),
        json.dumps({"type": "something.new"}),
        "not json",
    ])
    assert events == []
    assert state.error_message.startswith("Invalid message")


# ------------------------------------------------------------ lifecycle


class _FakeWS:
    def __init__(self, incoming=()):
        self.sent: list = []
        self.closed = False
        self._incoming = list(incoming)

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        item = self._incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        item = self._incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patch_dial(monkeypatch, ws, seen=None):
    async def dial(url, **kwargs):
        if seen is not None:
            seen.update(url=url, **kwargs)
        return ws

    monkeypatch.setattr(mod, "ws_connect", dial)


def test_connect_authenticates_in_the_header_and_waits_for_created(monkeypatch):
    ws = _FakeWS([json.dumps({"type": "transcript.created", "id": "83f2f6fd"})])
    seen: dict = {}
    _patch_dial(monkeypatch, ws, seen)

    async def run():
        adapter = XAISTTStream("xai-k")
        await adapter.connect(_config())
        assert seen["additional_headers"] == {"Authorization": "Bearer xai-k"}
        assert "xai-k" not in seen["url"]
        assert ws.sent == []  # nothing before transcript.created

    asyncio.run(run())


def test_connect_classifies_rejections_and_early_closes(monkeypatch):
    import websockets
    from websockets.frames import Close

    class _Resp:
        def __init__(self, status):
            self.status_code = status

    def rejected(status):
        async def dial(*_a, **_k):
            raise websockets.exceptions.InvalidStatus(_Resp(status))  # type: ignore[arg-type]
        return dial

    async def run():
        for status, recoverable in ((400, False), (401, False), (429, True), (503, True)):
            monkeypatch.setattr(mod, "ws_connect", rejected(status))
            with pytest.raises(ProviderStreamError) as exc:
                await XAISTTStream("k").connect(_config())
            assert exc.value.recoverable is recoverable and exc.value.code == str(status)

        ws = _FakeWS([
            json.dumps({"type": "error", "message": "pipeline failure"}),
            websockets.exceptions.ConnectionClosed(Close(1011, ""), None, None),
        ])
        _patch_dial(monkeypatch, ws)
        with pytest.raises(ProviderStreamError) as exc:
            await XAISTTStream("k").connect(_config())
        assert "pipeline failure" in str(exc.value) and exc.value.recoverable is True
        assert ws.closed is True

    asyncio.run(run())


def test_finish_sends_audio_done_and_events_end_on_transcript_done(monkeypatch):
    ws = _FakeWS([json.dumps({"type": "transcript.created", "id": "x"})])
    _patch_dial(monkeypatch, ws)

    async def run():
        adapter = XAISTTStream("k")
        await adapter.connect(_config())
        await adapter.send_audio(b"\x00\x01" * 1600)
        await adapter.finish()
        await adapter.finish()  # idempotent
        assert ws.sent[0] == b"\x00\x01" * 1600  # raw binary, no base64
        assert ws.sent[1:] == [json.dumps({"type": "audio.done"})]
        ws._incoming.extend([
            _partial("Hi.", 0.0, 0.8, is_final=True, speech_final=True),
            json.dumps({"type": "transcript.done", "text": "Hi.", "words": [],
                        "duration": 0.8}),
        ])
        events = [e async for e in adapter.events()]
        assert [e.text for e in events if isinstance(e, Transcript)] == ["Hi."]
        await adapter.close()
        await adapter.close()
        assert ws.closed is True

    asyncio.run(run())


def test_a_close_mid_session_is_a_recoverable_failure(monkeypatch):
    import websockets
    from websockets.frames import Close

    ws = _FakeWS([json.dumps({"type": "transcript.created", "id": "x"})])
    _patch_dial(monkeypatch, ws)

    async def run():
        adapter = XAISTTStream("k")
        await adapter.connect(_config())
        ws._incoming.extend([
            json.dumps({"type": "error", "message": "stream timeout"}),
            websockets.exceptions.ConnectionClosed(Close(1011, ""), None, None),
        ])
        with pytest.raises(ProviderStreamError) as exc:
            _ = [e async for e in adapter.events()]
        assert exc.value.recoverable is True and "stream timeout" in str(exc.value)

    asyncio.run(run())


# ----------------------------------------------------------------- batch


def test_batch_form_maps_the_unified_knobs():
    form = build_form(_config(
        model="grok-voice-transcribe-2.0-batch", language="en-US", diarization=True,
        keyterms=("Understand The Universe",),
        provider_params={"filler_words": True, "model": "grok-voice-transcribe-1.0"},
    ))
    assert form == {
        "model": "grok-voice-transcribe-2.0",  # suffix is ours, for the price
        "language": "en",
        "format": "true",  # ITN needs language; sent together
        "diarize": "true",
        "keyterm": ["Understand The Universe"],
        "filler_words": "true",
    }
    assert "format" not in build_form(_config(model="grok-voice-transcribe-2.0-batch"))


def test_batch_parses_the_documented_rest_response():
    payload = {
        "text": "The balance is $167,983.15. That is $23.4 kilograms.",
        "language": "en", "duration": 8.4,
        "words": [
            {"text": "The", "start": 0, "end": 0.24, "confidence": 0.33},
            {"text": "balance", "start": 0.24, "end": 0.64, "confidence": 0.67},
            {"text": "is", "start": 0.64, "end": 0.88, "confidence": 0.41},
            {"text": "$167,983.15.", "start": 0.88, "end": 4.8, "confidence": 0.07},
            {"text": "That", "start": 6.16, "end": 6.48, "confidence": 0.29},
            {"text": "is", "start": 6.48, "end": 6.64, "confidence": 0.4},
            {"text": "$23.4", "start": 6.64, "end": 7.52, "confidence": 0.07},
            {"text": "kilograms.", "start": 7.76, "end": 8.4, "confidence": 0.09},
        ],
    }
    t = parse_response(payload)
    assert t.text == payload["text"] and t.lang == "en" and t.end == 8.4
    assert len(t.words) == 8 and t.words[3].conf == 0.07 and t.words[7].end == 8.4


def test_batch_merges_multichannel_words_in_time_order():
    t = parse_response({
        "text": "Hello. Hi.", "language": "en", "duration": 2.0,
        "channels": [
            {"index": 0, "text": "Hello.", "words": [_w("Hello.", 0.1, 0.6)]},
            {"index": 1, "text": "Hi.", "words": [_w("Hi.", 0.05, 0.3)]},
        ],
    })
    assert [w.w for w in t.words] == ["Hi.", "Hello."]


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_client(monkeypatch, handler):
    def factory(**kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_batch_posts_fields_before_the_file(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": "Hi.", "language": "en", "duration": 1.0,
                                         "words": [_w("Hi.", 0.1, 0.5)]})

    _mock_client(monkeypatch, handler)

    async def run():
        t = await XAIBatch("k").transcribe(b"RIFF....", "audio/wav", _config(
            model="grok-voice-transcribe-2.0-batch", keyterms=("A", "B")))
        assert t.text == "Hi." and t.words[0].end == 0.5

    asyncio.run(run())
    assert seen["url"] == "https://api.x.ai/v1/stt"
    assert seen["auth"] == "Bearer k"
    body = seen["body"]
    # "fields sent after `file` may be ignored"
    assert body.index(b'name="model"') < body.index(b'name="file"')
    assert body.index(b'name="keyterm"') < body.index(b'name="file"')
    assert body.count(b'name="keyterm"') == 2


def test_batch_status_codes_are_classified(monkeypatch):
    async def run():
        for status, recoverable in ((400, False), (401, False), (413, False),
                                    (429, True), (502, True), (503, True)):
            _mock_client(monkeypatch, lambda _r, s=status: httpx.Response(
                s, json={"code": "x", "error": "nope"}))
            with pytest.raises(ProviderStreamError) as exc:
                await XAIBatch("k").transcribe(b"x", "audio/wav", _config())
            assert exc.value.code == str(status) and exc.value.recoverable is recoverable

    asyncio.run(run())


# ---------------------------------------------------------------- wiring


def test_slugs_resolve_to_the_right_mode_and_price():
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import (
        ResolveError,
        StreamRequest,
        resolve_batch,
        resolve_stream,
    )

    settings = Settings(keystore=KeyStoreKind.local, keys="k", _env_file=None,
                        xai_api_key="x")
    catalog = Catalog.load()
    stream = resolve_stream("xai/grok-voice-transcribe-2.0", StreamRequest(), settings, catalog)
    assert stream.config.model == "grok-voice-transcribe-2.0"
    assert stream.price_per_second_usd == pytest.approx(0.2 / 3600)
    batch = resolve_batch("xai/grok-voice-transcribe-2.0-batch", StreamRequest(), settings,
                          catalog)
    assert batch.config.model == "grok-voice-transcribe-2.0-batch"
    assert catalog.find("xai/grok-voice-transcribe-2.0-batch")["pricing"][
        "per_audio_hour_usd"] == 0.1
    with pytest.raises(ResolveError):  # streaming slug is not a batch model
        resolve_batch("xai/grok-voice-transcribe-2.0", StreamRequest(), settings, catalog)


def test_missing_key_is_not_configured():
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.providers.registry import ProviderNotConfigured

    settings = Settings(keystore=KeyStoreKind.local, keys="k", _env_file=None)
    with pytest.raises(ProviderNotConfigured):
        mod.build(settings)
