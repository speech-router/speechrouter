"""Telnyx parser fixtures -- JSON shapes verbatim from a live capture
(docs/providers/telnyx.md, verified 2026-08-04 against the Telnyx engine).
No socket required."""

from urllib.parse import parse_qs

from speechrouter_gateway.protocol import Transcript
from speechrouter_gateway.providers.base import STTConfig
from speechrouter_gateway.providers.telnyx.adapter import build_url, parse_message


def _frame(text="hello world", is_final=True, confidence=None):
    import json
    return json.dumps({"transcript": text, "confidence": confidence, "is_final": is_final})


def test_final_frame_maps_to_final_transcript():
    events = parse_message(_frame("Hello world.", is_final=True))
    assert len(events) == 1
    t = events[0]
    assert isinstance(t, Transcript)
    assert t.is_final is True
    assert t.text == "Hello world."
    assert t.words is None
    assert t.start is None and t.end is None


def test_empty_transcript_is_skipped():
    events = parse_message(_frame("", is_final=True))
    assert events == []


def test_whitespace_only_transcript_is_skipped():
    events = parse_message(_frame("   ", is_final=True))
    assert events == []


def test_error_frame_is_skipped():
    import json
    events = parse_message(json.dumps({"errors": [{"title": "bad"}]}))
    assert events == []


def test_include_raw_attaches_provider_payload():
    events = parse_message(_frame("hi"), include_raw=True)
    assert events[0].provider_raw is not None
    assert events[0].provider_raw["transcript"] == "hi"


def test_build_url_minimal():
    config = STTConfig(model="telnyx", encoding="linear16", sample_rate=16000)
    url = build_url(config)
    assert url.startswith("wss://api.telnyx.com/v2/speech-to-text/transcription?")
    qs = parse_qs(url.split("?", 1)[1])
    assert qs["transcription_engine"] == ["Telnyx"]
    assert qs["input_format"] == ["linear16"]
    assert qs["sample_rate"] == ["16000"]
    assert "language" not in qs  # auto-detect, not in URL


def test_build_url_with_language():
    config = STTConfig(model="telnyx", encoding="linear16", sample_rate=8000, language="en-US")
    url = build_url(config)
    qs = parse_qs(url.split("?", 1)[1])
    assert qs["language"] == ["en-US"]
    assert qs["sample_rate"] == ["8000"]


def test_build_url_auto_language_omitted():
    config = STTConfig(model="telnyx", encoding="linear16", sample_rate=16000, language="auto")
    url = build_url(config)
    qs = parse_qs(url.split("?", 1)[1])
    assert "language" not in qs


def test_build_url_mulaw():
    config = STTConfig(model="telnyx", encoding="mulaw", sample_rate=8000)
    url = build_url(config)
    qs = parse_qs(url.split("?", 1)[1])
    assert qs["input_format"] == ["mulaw"]


def test_build_url_provider_params_passthrough():
    config = STTConfig(
        model="telnyx", encoding="linear16", sample_rate=16000,
        provider_params={"custom_param": "value123"},
    )
    url = build_url(config)
    qs = parse_qs(url.split("?", 1)[1])
    assert qs["custom_param"] == ["value123"]
