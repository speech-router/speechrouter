"""Deepgram-compatible wire mode: params, events, and a full DG session."""

import json

from starlette.datastructures import QueryParams

from speechrouter_gateway.api.dg_compat import (
    dg_batch_response,
    dg_words,
    resolve_model,
    translate_params,
)
from speechrouter_gateway.protocol import Transcript, Word


def test_model_resolution():
    assert resolve_model("nova-3") == "deepgram/nova-3"
    assert resolve_model("nova-2-medical") == "deepgram/nova-2-medical"
    assert resolve_model("soniox/stt-rt-v5") == "soniox/stt-rt-v5"  # escape hatch


def test_translate_params_full_surface():
    params = QueryParams(
        "model=nova-3&encoding=mulaw&sample_rate=8000&channels=2&language=en"
        "&interim_results=true&diarize=true&keyterm=metoprolol&keyterm=SpeechRouter"
        "&keywords=aspirin:2&smart_format=true&utterance_end_ms=1200"
        "&fallbacks=soniox/stt-rt-v5,assemblyai/universal-3-5-pro"
    )
    slug, fallbacks, request = translate_params(params)
    assert slug == "deepgram/nova-3"
    assert fallbacks == ["soniox/stt-rt-v5", "assemblyai/universal-3-5-pro"]
    assert request.encoding == "mulaw" and request.sample_rate == 8000 and request.channels == 2
    assert request.interim_results is True
    assert request.diarization is True
    assert request.keyterms == ("metoprolol", "SpeechRouter", "aspirin")
    # DG-only knobs pass through to the deepgram adapter untouched
    assert request.provider_params["smart_format"] == "true"
    assert request.provider_params["utterance_end_ms"] == "1200"


def test_translate_params_dg_defaults():
    slug, fallbacks, request = translate_params(QueryParams("model=nova-3"))
    assert request.interim_results is False  # Deepgram's default, not ours
    assert request.diarization is False
    assert fallbacks == []


def test_non_deepgram_slug_drops_dg_knobs():
    _, _, request = translate_params(
        QueryParams("model=soniox/stt-rt-v5&smart_format=true&punctuate=true")
    )
    assert request.provider_params == {}


def test_words_and_batch_shape():
    transcript = Transcript(
        type="transcript", is_final=True, text="never lose a word",
        words=[Word(w="never", start=0.1, end=0.4, conf=0.98, speaker=1)],
        start=0.0, end=1.5,
    )
    body = dg_batch_response(transcript, "deepgram/nova-3", "dg_req1")
    alt = body["results"]["channels"][0]["alternatives"][0]
    assert alt["transcript"] == "never lose a word"
    assert alt["words"][0] == {
        "word": "never", "start": 0.1, "end": 0.4, "confidence": 0.98,
        "punctuated_word": "never", "speaker": 1,
    }
    assert body["metadata"]["duration"] == 1.5
    assert body["metadata"]["models"] == ["deepgram/nova-3"]
    assert dg_words(None) == []


def test_full_dg_session_over_websocket(monkeypatch):
    """An unmodified DG-style client: Token auth, binary audio, CloseStream —
    receives Results / UtteranceEnd / Metadata and a clean close."""
    from starlette.testclient import TestClient

    from speechrouter_gateway import main as main_module
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.providers import registry
    from tests.test_session_failover import SteadyAdapter

    monkeypatch.setattr(
        main_module, "settings",
        lambda: Settings(keystore=KeyStoreKind.local, keys="sk_test_dg", _env_file=None),
    )
    entry = registry.stt_stream_provider("deepgram")
    monkeypatch.setitem(
        registry._stt_stream, "deepgram",
        registry.RegisteredStream(lambda s: SteadyAdapter(), entry.capabilities),
    )

    with TestClient(main_module.app) as client:  # noqa: SIM117
        with client.websocket_connect(
            "/v1/listen?model=nova-3&encoding=linear16&sample_rate=16000",
            headers={"Authorization": "Token sk_test_dg"},
        ) as ws:
            ws.send_bytes(b"\x00\x01" * 800)
            ws.send_text(json.dumps({"type": "CloseStream"}))
            messages = []
            while True:
                try:
                    messages.append(json.loads(ws.receive_text()))
                except Exception:
                    break

    kinds = [m["type"] for m in messages]
    assert "Results" in kinds
    result = next(m for m in messages if m["type"] == "Results")
    assert result["is_final"] is True and result["speech_final"] is True
    assert result["channel"]["alternatives"][0]["transcript"]
    assert kinds[-1] == "Metadata"


def test_dg_prerecorded_route_registered():
    """Guards against the route silently missing: POST /v1/listen must
    match (auth error, not 404)."""
    from starlette.testclient import TestClient

    from speechrouter_gateway import main as main_module

    with TestClient(main_module.app) as client:
        r = client.post("/v1/listen?model=nova-3", content=b"x",
                        headers={"Authorization": "Token bad", "Content-Type": "audio/wav"})
        assert r.status_code != 404
        assert r.json()["error"]["code"] == "auth_failed"
