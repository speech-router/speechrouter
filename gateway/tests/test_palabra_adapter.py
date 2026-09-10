"""Palabra parser fixtures — JSON shapes taken from the documented STT wire
(docs/providers/palabra.md, verified 2026-08-13 against docs.palabra.ai and
the official SDK palabra-ai-python v2.1.0). No socket required."""

import json
from urllib.parse import parse_qs

import pytest

from speechrouter_gateway.protocol import Transcript
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.palabra.adapter import (
    PalabraSTTStream,
    build_url,
    parse_message,
    redact,
    translation_nudges,
)


def _frame(text="Hello world how are", is_eos=False, kind="transcription", language="en"):
    return json.dumps(
        {
            "message_type": kind,
            "transcription_id": "a1b2c3d4",
            "language": language,
            "is_eos": is_eos,
            "segment": {"text": text, "start_time": 0.32, "end_time": 1.84},
            "delta": {"text": "how are", "start_time": 1.20, "end_time": 1.84},
        }
    )


def test_final_frame_maps_to_final_transcript():
    events = parse_message(_frame("Hello world.", is_eos=True))
    assert len(events) == 1
    t = events[0]
    assert isinstance(t, Transcript)
    assert t.is_final is True
    assert t.text == "Hello world."
    assert t.lang == "en"


def test_partial_frame_is_not_final():
    (t,) = parse_message(_frame(is_eos=False))
    assert t.is_final is False


def test_segment_times_are_seconds_and_words_are_absent():
    (t,) = parse_message(_frame(is_eos=True))
    assert t.start == 0.32 and t.end == 1.84
    # Palabra gives segment-level times only — no word timestamps at all.
    assert t.words is None


def test_delta_is_ignored_in_favour_of_segment():
    """enable_filler_filter (on by default) may rewrite the segment tail
    mid-stream, so `delta` is only correct in the non-default configuration.
    The whole segment is authoritative under both."""
    (t,) = parse_message(_frame("Hello world how are you", is_eos=True))
    assert t.text == "Hello world how are you"
    assert "how are" != t.text


def test_empty_and_whitespace_transcripts_are_skipped():
    assert parse_message(_frame("")) == []
    assert parse_message(_frame("   ")) == []


def test_translated_transcription_is_tagged_with_target_language():
    """Translated frames only arrive when the caller set translate_languages.
    They ride as Transcripts tagged by `lang`, so the client can tell them
    from the source stream — the Soniox model."""
    events = parse_message(
        _frame("Hola mundo", is_eos=True, kind="translated_transcription", language="es")
    )
    assert len(events) == 1
    assert events[0].lang == "es"
    assert events[0].text == "Hola mundo"
    assert events[0].is_final is True


# --------------------------------------------------------- translation dedup


def test_translated_final_end_is_nudged_past_its_source():
    """A translated final copies the source final's `end`, and the session
    layer drops any final that does not advance past the previous one. Without
    the nudge the translation is swallowed above this adapter and the client
    sees nothing — so it is offset by one slot per target language."""
    nudge = translation_nudges({"translate_languages": "es,de"})
    (source,) = parse_message(_frame("Hello world.", is_eos=True), translation_nudge=nudge)
    (es,) = parse_message(
        _frame("Hola mundo.", is_eos=True, kind="translated_transcription", language="es"),
        translation_nudge=nudge,
    )
    (de,) = parse_message(
        _frame("Hallo Welt.", is_eos=True, kind="translated_transcription", language="de"),
        translation_nudge=nudge,
    )
    assert source.end == 1.84  # the source stream keeps the vendor's timestamp
    assert es.end == 1.841
    assert de.end == 1.842
    # Strictly increasing in arrival order == every one of them clears the
    # session layer's monotonic dedup gate.
    assert source.end < es.end < de.end


def test_translation_nudge_is_deterministic_across_adapter_instances():
    """The slot comes from the caller's own target list, not from arrival
    order, so a replay into a fresh adapter after failover reproduces the same
    `end` — and stays deduplicated."""
    assert translation_nudges({"translate_languages": "es,de"}) == {"es": 0.001, "de": 0.002}
    assert translation_nudges({"translate_languages": ["ES", " de "]}) == {"es": 0.001, "de": 0.002}
    assert translation_nudges({}) == {}


def test_translated_partials_keep_the_vendor_timestamp():
    """Partials never reach the dedup gate, so they are not fabricated."""
    (t,) = parse_message(
        _frame("Hola", is_eos=False, kind="translated_transcription", language="es"),
        translation_nudge=translation_nudges({"translate_languages": "es"}),
    )
    assert t.end == 1.84


def test_unlisted_target_language_still_clears_the_gate():
    """A target the caller did not list (or a code the server spells its own
    way) falls back to one slot — delivered, not silently dropped."""
    (t,) = parse_message(
        _frame("Ciao", is_eos=True, kind="translated_transcription", language="it"),
        translation_nudge=translation_nudges({"translate_languages": "es"}),
    )
    assert t.end == 1.841


def test_unknown_message_types_are_skipped():
    assert parse_message(json.dumps({"message_type": "pipeline_timings", "data": {}})) == []


def test_error_frame_raises_unrecoverable_provider_error():
    with pytest.raises(ProviderStreamError) as exc:
        parse_message(json.dumps({"message_type": "error", "code": "BAD", "desc": "nope"}))
    assert "nope" in str(exc.value)
    assert exc.value.code == "BAD"
    assert exc.value.recoverable is False


def test_pacing_warning_is_not_fatal():
    """AUDIO_STREAM_TOO_FAST and friends are complaints, not stream death."""
    events = parse_message(
        json.dumps({"message_type": "warning", "code": "AUDIO_STREAM_TOO_FAST", "message": "slow"})
    )
    assert events == []


def test_include_raw_attaches_provider_payload():
    (t,) = parse_message(_frame("hi", is_eos=True), include_raw=True)
    assert t.provider_raw is not None
    assert t.provider_raw["transcription_id"] == "a1b2c3d4"


def test_include_raw_off_by_default():
    (t,) = parse_message(_frame("hi", is_eos=True))
    assert t.provider_raw is None


# ---------------------------------------------------------------- URL build


def test_build_url_minimal():
    config = STTConfig(model="asr-v1", encoding="linear16", sample_rate=16000)
    url = build_url(config, "key-123")
    assert url.startswith("wss://stream.palabra.ai/asr/v1/speech-to-text/stream?")
    qs = parse_qs(url.split("?", 1)[1])
    assert qs["token"] == ["key-123"]
    assert qs["format"] == ["pcm_s16le"]
    assert qs["sample_rate"] == ["16000"]
    assert "language" not in qs  # autodetect stays out of the URL


def test_build_url_with_language():
    config = STTConfig(model="asr-v1", encoding="linear16", sample_rate=8000, language="en")
    qs = parse_qs(build_url(config, "k").split("?", 1)[1])
    assert qs["language"] == ["en"]
    assert qs["sample_rate"] == ["8000"]


def test_build_url_auto_language_omitted():
    config = STTConfig(model="asr-v1", encoding="linear16", sample_rate=16000, language="auto")
    assert "language" not in parse_qs(build_url(config, "k").split("?", 1)[1])


def test_build_url_encoding_map():
    for ours, theirs in (("mulaw", "mulaw"), ("alaw", "alaw"), ("linear32", "pcm_s32le")):
        config = STTConfig(model="asr-v1", encoding=ours, sample_rate=8000)
        qs = parse_qs(build_url(config, "k").split("?", 1)[1])
        assert qs["format"] == [theirs]


def test_build_url_forwards_provider_params():
    config = STTConfig(
        model="asr-v1",
        encoding="linear16",
        sample_rate=16000,
        provider_params={"translate_languages": "es,de"},
    )
    qs = parse_qs(build_url(config, "k").split("?", 1)[1])
    assert qs["translate_languages"] == ["es,de"]


def test_build_url_serialises_bools_and_lists():
    """provider_params arrive as JSON, so bools must not become 'True'."""
    config = STTConfig(
        model="asr-v1",
        encoding="linear16",
        sample_rate=16000,
        provider_params={"enable_filler_filter": False, "translate_languages": ["es", "de"]},
    )
    qs = parse_qs(build_url(config, "k").split("?", 1)[1])
    assert qs["enable_filler_filter"] == ["false"]
    assert qs["translate_languages"] == ["es,de"]


def test_build_url_ignores_reserved_params():
    """A second `sample_rate` in the query would leave the server picking
    between two values, one of which does not match the audio we send."""
    config = STTConfig(
        model="asr-v1",
        encoding="linear16",
        sample_rate=16000,
        provider_params={"sample_rate": 8000, "token": "stolen", "format": "mulaw",
                         "language": "de", "enable_filler_filter": False},
    )
    qs = parse_qs(build_url(config, "key-123").split("?", 1)[1])
    assert qs["sample_rate"] == ["16000"]
    assert qs["token"] == ["key-123"]
    assert qs["format"] == ["pcm_s16le"]
    assert "language" not in qs
    assert qs["enable_filler_filter"] == ["false"]  # non-reserved keys still pass


def test_redact_hides_the_key_from_error_text():
    """The key travels in the query string, so anything quoting the URL back
    (websockets' InvalidURI) must not reach a log verbatim."""
    url = build_url(STTConfig(model="asr-v1", encoding="linear16", sample_rate=16000), "secret")
    assert "secret" not in redact(f"invalid URI: {url}", "secret")
    assert "***" in redact(f"invalid URI: {url}", "secret")


# ---------------------------------------------------------------- lifecycle


def test_stereo_is_rejected_before_dialing():
    """The wire carries no channel count and the server assumes mono, so
    interleaved stereo would transcribe as garbage instead of failing."""
    import asyncio

    async def run():
        adapter = PalabraSTTStream("k")
        with pytest.raises(ProviderStreamError) as exc:
            await adapter.connect(
                STTConfig(model="asr-v1", encoding="linear16", sample_rate=16000, channels=2)
            )
        assert exc.value.recoverable is False

    asyncio.run(run())


def test_send_audio_rechunks_to_320ms():
    """Client framing is not forwarded verbatim — Palabra wants 320ms frames."""
    import asyncio

    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send(self, chunk):
            self.sent.append(chunk)

    async def run():
        adapter = PalabraSTTStream("k")
        adapter._ws = FakeWS()
        adapter._chunk_bytes = 10240  # 320ms of 16k mono linear16
        adapter._byte_rate = 0  # pacing off; this test is about framing
        for _ in range(4):
            await adapter.send_audio(b"\x01" * 4096)  # 128ms client frames
        # 16384 bytes in -> one full 320ms frame out, the rest held back.
        assert [len(f) for f in adapter._ws.sent] == [10240]
        assert len(adapter._pending) == 16384 - 10240

    asyncio.run(run())


def test_send_audio_paces_a_failover_replay():
    """The ring replay after a failover arrives as fast as the feeder loop
    runs; the bucket caps ingest at _MAX_REALTIME_FACTOR x realtime."""
    import asyncio

    from speechrouter_gateway.providers.palabra import adapter as mod

    class FakeWS:
        def __init__(self):
            self.sent = 0

        async def send(self, chunk):
            self.sent += 1

    async def run():
        adapter = PalabraSTTStream("k")
        adapter._ws = FakeWS()
        adapter._chunk_bytes = 10240
        adapter._byte_rate = 32000  # 16k mono linear16
        loop = asyncio.get_running_loop()
        started = loop.time()
        # 10s of audio, the default ring buffer, replayed in one burst.
        await adapter.send_audio(b"\x02" * (32000 * 10))
        elapsed = loop.time() - started
        assert adapter._ws.sent == 31  # 10s / 320ms, floor
        # 31 frames x 320ms / 4x == 2.48s of bucket time, minus 2s of credit.
        expected = 31 * 0.32 / mod._MAX_REALTIME_FACTOR - mod._MAX_BURST_SECONDS
        assert expected * 0.5 < elapsed < expected + 1.0
        assert elapsed < 10  # never throttled all the way down to realtime

    asyncio.run(run())


def test_finish_pads_with_silence_then_closes():
    """Live-verified 2026-08-13: closing the socket outright loses the last
    utterance — it stays a partial forever. Feeding silence makes Palabra's
    endpointer fire and emit the final. Regression test for that fix."""
    import asyncio

    class FakeWS:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def send(self, chunk):
            self.sent.append(chunk)

        async def close(self):
            self.closed = True

    async def run():
        adapter = PalabraSTTStream("k")
        adapter._ws = FakeWS()
        adapter._silence_chunk = b"\x00" * 640
        adapter._SILENCE_FLUSH_SECONDS = 0.64  # two 320ms chunks
        adapter._FINISH_GRACE_SECONDS = 0
        await adapter.finish()
        assert adapter._finished is True
        assert adapter._ws.sent == [b"\x00" * 640] * 2
        assert adapter._ws.closed is True

    asyncio.run(run())


def test_silence_chunk_matches_encoding():
    """Zero bytes are silence for linear PCM but a buzz in mulaw/alaw, whose
    silent codes are 0xFF and 0xD5."""
    from speechrouter_gateway.providers.palabra.adapter import _silence_chunk

    pcm = _silence_chunk(STTConfig(model="m", encoding="linear16", sample_rate=16000))
    assert len(pcm) == 16000 * 0.32 * 2
    assert set(pcm) == {0x00}

    ulaw = _silence_chunk(STTConfig(model="m", encoding="mulaw", sample_rate=8000))
    assert len(ulaw) == 8000 * 0.32
    assert set(ulaw) == {0xFF}

    alaw = _silence_chunk(STTConfig(model="m", encoding="alaw", sample_rate=8000))
    assert set(alaw) == {0xD5}


def test_finish_and_close_are_idempotent():
    import asyncio

    class FakeWS:
        def __init__(self):
            self.close_calls = 0

        async def close(self):
            self.close_calls += 1

    async def run():
        adapter = PalabraSTTStream("k")
        adapter._ws = FakeWS()
        adapter._silence_chunk = b""  # skip the flush; this test is about close
        adapter._FINISH_GRACE_SECONDS = 0
        await adapter.finish()
        await adapter.finish()
        await adapter.close()
        await adapter.close()
        assert adapter._ws.close_calls == 2  # one from finish, one from close

    asyncio.run(run())


def test_connect_rejections_are_classified_by_http_status():
    """401 is a bad key — retrying or failing over to another Palabra session
    cannot help. 409 means a session is already live for this identity, which
    a retry after backoff may clear."""
    import asyncio
    from types import SimpleNamespace

    import websockets

    from speechrouter_gateway.providers.palabra import adapter as mod

    async def run():
        for status, recoverable in ((401, False), (409, True)):
            async def boom(*_args, _status=status, **_kwargs):
                raise websockets.exceptions.InvalidStatus(
                    SimpleNamespace(status_code=_status, headers={})
                )

            monkeyed = mod.ws_connect
            mod.ws_connect = boom
            try:
                adapter = PalabraSTTStream("k")
                with pytest.raises(ProviderStreamError) as exc:
                    await adapter.connect(
                        STTConfig(model="asr-v1", encoding="linear16", sample_rate=16000)
                    )
            finally:
                mod.ws_connect = monkeyed
            assert exc.value.code == str(status)
            assert exc.value.recoverable is recoverable

    asyncio.run(run())


def test_events_classify_the_close_code():
    """1008 is a policy violation — the same request will be refused again,
    so it must not look recoverable to the failover engine."""
    import asyncio

    import websockets
    from websockets.frames import Close

    class ClosingWS:
        def __init__(self, code):
            self._code = code

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise websockets.exceptions.ConnectionClosed(Close(self._code, "bye"), None, None)

    async def run():
        for code, recoverable in ((1008, False), (1011, True)):
            adapter = PalabraSTTStream("k")
            adapter._ws = ClosingWS(code)
            with pytest.raises(ProviderStreamError) as exc:
                async for _ in adapter.events():
                    pass
            assert exc.value.code == str(code)
            assert exc.value.recoverable is recoverable

        # After finish() the close is the expected end of stream, not a failure.
        adapter = PalabraSTTStream("k")
        adapter._ws = ClosingWS(1000)
        adapter._finished = True
        assert [e async for e in adapter.events()] == []

    asyncio.run(run())


def test_error_and_warning_payloads_nested_under_data():
    """The SDK's parser puts error/warning fields under `data`; the flat shape
    shows up too, so both are read."""
    with pytest.raises(ProviderStreamError) as exc:
        parse_message(
            json.dumps(
                {"message_type": "error", "data": {"code": "LIMIT", "desc": "quota"}}
            )
        )
    assert exc.value.code == "LIMIT"
    assert "quota" in str(exc.value)

    assert parse_message(
        json.dumps(
            {"message_type": "warning", "data": {"code": "AUDIO_STREAM_STALLED"}}
        )
    ) == []


def test_unknown_region_is_rejected_at_build_time():
    from speechrouter_gateway.providers.registry import ProviderNotConfigured

    with pytest.raises(ProviderNotConfigured):
        PalabraSTTStream("k", region="mars")


def test_unsupported_language_400_carries_the_servers_reason():
    """Live 2026-09-10: an unknown `language` is refused on the upgrade with
    HTTP 400 and a body naming the accepted codes. That text is the caller's
    to see (invalid_request, forwarded verbatim by the session), the key is
    not, and retrying Palabra cannot help."""
    import asyncio
    from types import SimpleNamespace

    import websockets

    from speechrouter_gateway.providers.palabra import adapter as mod

    body = (b'invalid parameter "language": unsupported language code "xx"; '
            b'one of: ar, de, en, es, fr, hi, it, ja, ko, nl, pt, ru, zh, auto')

    async def boom(*_args, **_kwargs):
        raise websockets.exceptions.InvalidStatus(
            # websockets hands the body over as a bytearray, not bytes
            SimpleNamespace(status_code=400, headers={}, body=bytearray(body + b" token=sekret\n"))
        )

    async def run():
        monkeyed = mod.ws_connect
        mod.ws_connect = boom
        try:
            adapter = PalabraSTTStream("sekret")
            with pytest.raises(ProviderStreamError) as exc:
                await adapter.connect(
                    STTConfig(model="asr-v1", encoding="linear16", sample_rate=16000,
                              language="xx")
                )
        finally:
            mod.ws_connect = monkeyed
        assert exc.value.code == "invalid_request"
        assert exc.value.recoverable is False
        assert 'unsupported language code "xx"' in str(exc.value)
        assert "one of: ar, de" in str(exc.value)
        assert "sekret" not in str(exc.value)
        assert "bytearray" not in str(exc.value) and "\n" not in str(exc.value)

    asyncio.run(run())


def test_ws_base_setting_overrides_the_region_endpoint():
    """SPEECHROUTER_PALABRA_WS_BASE points a gateway at a non-prod Palabra
    environment; the region table is only the default."""
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.providers.palabra.adapter import WS_BASE, build

    custom = "wss://stt.example.invalid/asr/v1/speech-to-text/stream"
    common = dict(keystore=KeyStoreKind.local, keys="k", _env_file=None, palabra_api_key="x")
    assert build(Settings(**common, palabra_ws_base=custom))._ws_base == custom
    assert build(Settings(**common))._ws_base == WS_BASE


# ---------------------------------------------------------------- wiring


def test_provider_is_registered_and_resolvable():
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import StreamRequest, resolve_stream

    settings = Settings(
        keystore=KeyStoreKind.local, keys="k", _env_file=None, palabra_api_key="x"
    )
    attempt = resolve_stream(
        "palabra/asr-v1", StreamRequest(encoding="linear16", sample_rate=16000),
        settings, Catalog.load(),
    )
    assert attempt.slug == "palabra/asr-v1"
    assert attempt.config.model == "asr-v1"
    # $0.002/min of audio -> per-second derived by the catalog
    assert attempt.price_per_second_usd == pytest.approx(0.002 / 60)


def test_missing_credentials_are_rejected_before_dialing():
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import ResolveError, StreamRequest, resolve_stream

    settings = Settings(keystore=KeyStoreKind.local, keys="k", _env_file=None)
    with pytest.raises(ResolveError):
        resolve_stream(
            "palabra/asr-v1", StreamRequest(encoding="linear16", sample_rate=16000),
            settings, Catalog.load(),
        )


def test_diarization_request_is_rejected():
    """No speaker labels on this endpoint — the resolver must refuse before
    a socket is opened rather than silently dropping the request."""
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import ResolveError, StreamRequest, resolve_stream

    settings = Settings(
        keystore=KeyStoreKind.local, keys="k", _env_file=None, palabra_api_key="x"
    )
    with pytest.raises(ResolveError):
        resolve_stream(
            "palabra/asr-v1",
            StreamRequest(encoding="linear16", sample_rate=16000, diarization=True),
            settings,
            Catalog.load(),
        )
