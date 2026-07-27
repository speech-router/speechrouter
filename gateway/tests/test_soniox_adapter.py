"""Soniox token-algebra fixtures — shapes from docs/providers/soniox.md."""

import pytest

from speechrouter_gateway.protocol import Transcript, UtteranceEnd
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.soniox.adapter import (
    _tokens_to_words,
    _TokenState,
    build_config_message,
)


def _token(text, start_ms=None, end_ms=None, is_final=False, **kw):
    token = {"text": text, "is_final": is_final, **kw}
    if start_ms is not None:
        token["start_ms"] = start_ms
        token["end_ms"] = end_ms
    return token


def test_nonfinals_produce_interim_and_are_replaced():
    state = _TokenState()
    events = state.process({"tokens": [_token("How're", 0, 300)]})
    assert [type(e) for e in events] == [Transcript]
    assert events[0].is_final is False
    assert events[0].text == "How're"

    # next message wholesale-replaces the provisional tail ("How're" -> "How are")
    events = state.process(
        {"tokens": [_token("How", 0, 200), _token(" are", 200, 350)]}
    )
    interim = events[-1]
    assert interim.is_final is False
    assert interim.text == "How are"


def test_endpoint_marker_flushes_finals_and_emits_utterance_end():
    state = _TokenState()
    state.process({"tokens": [_token("Hel", 0, 200), _token("lo", 200, 400)]})  # provisional
    events = state.process(
        {
            "tokens": [
                _token("Hel", 0, 200, is_final=True, confidence=0.97, speaker="1"),
                _token("lo", 200, 400, is_final=True, confidence=0.95, speaker="1"),
                _token(" world", 400, 800, is_final=True, confidence=0.9, speaker="1"),
                _token("<end>", is_final=True),
            ]
        }
    )
    assert [type(e) for e in events] == [Transcript, UtteranceEnd]
    final = events[0]
    assert final.is_final is True
    assert final.text == "Hello world"
    assert "<end>" not in final.text
    # subword merge: Hel+lo one word, ' world' starts the next
    assert [w.w for w in final.words] == ["Hello", "world"]
    assert final.words[0].start == 0.0 and final.words[0].end == 0.4
    assert final.words[0].speaker == 1  # string "1" -> int
    assert final.words[0].conf == 0.95  # min of subword confidences
    assert events[1].at == 0.8


def test_monotonic_dedup_drops_late_overlapping_finals():
    state = _TokenState()
    state.process(
        {"tokens": [_token("one", 0, 500, is_final=True), _token("<end>", is_final=True)]}
    )
    events = state.process({"tokens": [_token("one", 100, 450, is_final=True)]})  # stale re-send
    finals = [e for e in events if isinstance(e, Transcript) and e.is_final]
    assert finals == []


def test_finished_message_flushes_pending():
    state = _TokenState()
    state.process({"tokens": [_token("tail", 0, 300)]})
    events = state.process(
        {"tokens": [_token("tail", 0, 300, is_final=True)], "finished": True}
    )
    finals = [e for e in events if isinstance(e, Transcript) and e.is_final]
    assert len(finals) == 1 and finals[0].text == "tail"


def test_error_payload_raises_typed():
    state = _TokenState()
    with pytest.raises(ProviderStreamError) as recoverable:
        state.process({"tokens": [], "error_code": 503, "error_type": "service_unavailable",
                       "error_message": "restart"})
    assert recoverable.value.recoverable is True

    with pytest.raises(ProviderStreamError) as fatal:
        state.process({"tokens": [], "error_code": 401, "error_type": "unauthenticated",
                       "error_message": "bad key"})
    assert fatal.value.recoverable is False


def test_tokens_to_words_handles_leading_space_boundaries():
    words = _tokens_to_words(
        [
            _token("Beau", 0, 100),
            _token("ti", 100, 150),
            _token("ful", 150, 250),
            _token(" day", 250, 500),
        ]
    )
    assert [w.w for w in words] == ["Beautiful", "day"]


def test_config_message_shape():
    config = STTConfig(
        model="stt-rt-v5", encoding="linear16", sample_rate=16000,
        language="en", diarization=True, keyterms=("Celebrex",),
        provider_params={"max_endpoint_delay_ms": 1500},
    )
    message = build_config_message("key123", config)
    assert message["api_key"] == "key123"
    assert message["audio_format"] == "pcm_s16le"
    assert message["language_hints"] == ["en"]
    assert message["language_hints_strict"] is True
    assert message["enable_speaker_diarization"] is True
    assert message["enable_endpoint_detection"] is True
    assert message["context"] == {"terms": ["Celebrex"]}
    assert message["max_endpoint_delay_ms"] == 1500
