"""Batch infra: formatters, endpoint plumbing, Deepgram/Soniox batch parsing."""

import pytest
from fastapi.testclient import TestClient

from speechrouter_gateway.api import formatters
from speechrouter_gateway.protocol import Transcript, Word
from speechrouter_gateway.providers.base import (
    Capabilities,
    ProviderStreamError,
    STTBatchProvider,
    STTConfig,
)
from speechrouter_gateway.providers.deepgram.batch import build_params, parse_response
from speechrouter_gateway.providers.soniox.batch import build_job, parse_transcript


def _transcript(**kw):
    defaults = dict(
        type="transcript", is_final=True, text="hello world again",
        words=[
            Word(w="hello", start=0.1, end=0.5),
            Word(w="world", start=0.6, end=1.0),
            Word(w="again", start=2.5, end=3.0),  # >1s gap -> new cue
        ],
        start=0.0, end=3.0,
    )
    defaults.update(kw)
    return Transcript(**defaults)


def test_srt_cue_split_on_gap_and_timestamps():
    srt = formatters.to_srt(_transcript())
    blocks = [b for b in srt.split("\n\n") if b.strip()]
    assert len(blocks) == 2
    assert blocks[0].startswith("1\n00:00:00,100 --> 00:00:01,000\nhello world")
    assert blocks[1].startswith("2\n00:00:02,500 --> 00:00:03,000\nagain")


def test_vtt_header_and_dot_timestamps():
    vtt = formatters.to_vtt(_transcript())
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.100 --> 00:00:01.000" in vtt


def test_formats_without_words_degrade_gracefully():
    bare = _transcript(words=None)
    assert "hello world again" in formatters.to_srt(bare)
    assert formatters.to_verbose_json(bare, "x/y")["duration"] == 3.0


# ---- Deepgram batch ----

def test_deepgram_batch_params_and_parse():
    config = STTConfig(model="nova-3", encoding="linear16", sample_rate=16000,
                       language="en", diarization=True, keyterms=("Zyrtec",))
    params = dict(build_params(config))
    assert params["model"] == "nova-3" and params["diarize"] == "true"
    assert params["keyterm"] == "Zyrtec"

    payload = {
        "metadata": {"duration": 2.5},
        "results": {"channels": [{
            "detected_language": "en",
            "alternatives": [{
                "transcript": "Hello world.",
                "confidence": 0.98,
                "words": [
                    {"word": "hello", "punctuated_word": "Hello", "start": 0.1, "end": 0.5,
                     "confidence": 0.99, "speaker": 0},
                    {"word": "world", "punctuated_word": "world.", "start": 0.6, "end": 1.0,
                     "confidence": 0.97, "speaker": 0},
                ],
            }],
        }]},
    }
    t = parse_response(payload)
    assert t.text == "Hello world."
    assert t.end == 2.5 and t.lang == "en"
    assert [w.w for w in t.words] == ["Hello", "world."]
    assert t.words[0].speaker == 0


# ---- Soniox batch ----

def test_soniox_job_shape_and_transcript_parse():
    config = STTConfig(model="stt-async-v5", encoding="linear16", sample_rate=16000,
                       language="es", diarization=True, keyterms=("Celebrex",))
    job = build_job("file-123", config)
    assert job["file_id"] == "file-123"
    assert job["language_hints"] == ["es"]
    assert job["enable_speaker_diarization"] is True
    assert job["context"] == {"terms": ["Celebrex"]}

    payload = {
        "id": "j1",
        "text": "Hello world",
        "tokens": [
            {"text": "Hel", "start_ms": 0, "end_ms": 200, "confidence": 0.99, "speaker": "1"},
            {"text": "lo", "start_ms": 200, "end_ms": 400, "confidence": 0.98, "speaker": "1"},
            {"text": " world", "start_ms": 400, "end_ms": 900, "confidence": 0.97, "speaker": "2"},
        ],
    }
    t = parse_transcript(payload)
    assert t.text == "Hello world"
    assert [w.w for w in t.words] == ["Hello", "world"]
    assert t.words[1].speaker == 2
    assert t.end == 0.9


# ---- endpoint plumbing with a fake provider ----

@pytest.fixture()
def client(monkeypatch):
    from speechrouter_gateway.main import app
    from speechrouter_gateway.providers import registry
    from speechrouter_gateway.router.catalog import Catalog

    class FakeBatch(STTBatchProvider):
        name = "fakeb"
        capabilities = Capabilities(batch=True, diarization=False)

        async def transcribe(self, audio, content_type, config):
            if config.model == "boom":
                raise ProviderStreamError("upstream 500", recoverable=True, provider="fakeb")
            return _transcript()

    monkeypatch.setitem(
        registry._stt_batch, "fakeb",
        registry.RegisteredBatch(lambda s: FakeBatch(), FakeBatch.capabilities),
    )
    entries = [
        {"slug": "fakeb/ok", "provider": "fakeb", "kind": "stt", "modes": ["batch"],
         "pricing": {}, "capabilities": {}},
        {"slug": "fakeb/boom", "provider": "fakeb", "kind": "stt", "modes": ["batch"],
         "pricing": {}, "capabilities": {}},
    ]
    with TestClient(app) as c:
        app.state.catalog = Catalog(entries)
        app.state.settings = app.state.settings.model_copy(update={"keys": "sk_test"})
        from speechrouter_gateway.auth import build_keystore
        app.state.keystore = build_keystore(app.state.settings)
        yield c


AUTH = {"Authorization": "Bearer sk_test"}


def test_endpoint_json_roundtrip(client):
    r = client.post(
        "/v1/audio/transcriptions",
        headers=AUTH,
        data={"model": "fakeb/ok"},
        files={"file": ("a.wav", b"RIFFxxxx", "audio/wav")},
    )
    assert r.status_code == 200
    assert r.json() == {"text": "hello world again"}


def test_endpoint_srt_and_auth_and_validation(client):
    r = client.post(
        "/v1/audio/transcriptions", headers=AUTH,
        data={"model": "fakeb/ok", "response_format": "srt"},
        files={"file": ("a.wav", b"x", "audio/wav")},
    )
    assert r.status_code == 200 and "-->" in r.text

    unauth = client.post("/v1/audio/transcriptions", data={"model": "fakeb/ok"},
                         files={"file": ("a.wav", b"x", "audio/wav")})
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "auth_failed"

    both = client.post("/v1/audio/transcriptions", headers=AUTH,
                       data={"model": "fakeb/ok", "url": "http://x"},
                       files={"file": ("a.wav", b"x", "audio/wav")})
    assert both.status_code == 400

    missing = client.post("/v1/audio/transcriptions", headers=AUTH,
                          data={"model": "nosuch/model"},
                          files={"file": ("a.wav", b"x", "audio/wav")})
    assert missing.status_code == 404


def test_endpoint_provider_error_maps_to_502(client):
    r = client.post("/v1/audio/transcriptions", headers=AUTH,
                    data={"model": "fakeb/boom"},
                    files={"file": ("a.wav", b"x", "audio/wav")})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "provider_error"
