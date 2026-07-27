"""Mistral realtime fixtures — shapes verified from SDK source (docs/providers/mistral.md)."""

import pytest

from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.mistral.adapter import _StreamState, build_session_update


def test_delta_accumulates_into_interim_hypothesis():
    state = _StreamState()
    events = state.process({"type": "transcription.text.delta", "text": "Hel"})
    assert events[0].is_final is False and events[0].text == "Hel"
    events = state.process({"type": "transcription.text.delta", "text": "lo"})
    assert events[0].text == "Hello"


def test_segment_finalizes_and_resets_hypothesis():
    state = _StreamState()
    state.process({"type": "transcription.language", "audio_language": "en"})
    state.process({"type": "transcription.text.delta", "text": "Hello"})
    events = state.process({"type": "transcription.segment", "text": "Hello.",
                            "start": 0.0, "end": 1.92, "speaker_id": None})
    assert events[0].is_final is True
    assert events[0].text == "Hello." and events[0].end == 1.92
    assert events[0].lang == "en"
    assert state.hypothesis == ""  # segment consumed the delta buffer


def test_done_emits_final_only_without_prior_segments():
    with_segments = _StreamState()
    with_segments.process({"type": "transcription.segment", "text": "Hi", "start": 0, "end": 1})
    events = with_segments.process({"type": "transcription.done", "text": "Hi",
                                    "language": "en", "usage": {}})
    assert events == [] and with_segments.done is True  # no duplicate final

    delta_only = _StreamState()
    delta_only.process({"type": "transcription.text.delta", "text": "Hi"})
    events = delta_only.process({"type": "transcription.done", "text": "Hi there",
                                 "language": "en", "usage": {}})
    assert events[0].is_final is True and events[0].text == "Hi there"


def test_error_shapes_and_recoverability():
    state = _StreamState()
    with pytest.raises(ProviderStreamError) as server_err:
        state.process({"type": "error", "error": {"message": "overloaded", "code": 503}})
    assert server_err.value.recoverable is True
    with pytest.raises(ProviderStreamError) as client_err:
        state.process({"type": "error", "error": {"message": {"detail": "bad"}, "code": 400}})
    assert client_err.value.recoverable is False


def test_session_update_shape():
    config = STTConfig(model="voxtral-mini-transcribe-realtime-2602", encoding="linear16",
                       sample_rate=16000,
                       provider_params={"target_streaming_delay_ms": 480})
    update = build_session_update(config)
    assert update["type"] == "session.update"
    assert update["session"]["audio_format"] == {"encoding": "pcm_s16le", "sample_rate": 16000}
    assert update["session"]["target_streaming_delay_ms"] == 480
