"""Deepgram parser fixtures — JSON shapes verbatim from official docs
(docs/providers/deepgram.md). No socket required."""

import json

from speechrouter_gateway.protocol import SpeechStarted, Transcript, UtteranceEnd
from speechrouter_gateway.providers.base import STTConfig
from speechrouter_gateway.providers.deepgram.adapter import build_url, parse_message


def _results(text="hello world", is_final=False, speech_final=False, start=0.0, duration=1.98,
             words=None, **channel_extra):
    return json.dumps({
        "type": "Results",
        "channel_index": [0, 1],
        "duration": duration,
        "start": start,
        "is_final": is_final,
        "speech_final": speech_final,
        "from_finalize": False,
        "channel": {
            "alternatives": [{
                "transcript": text,
                "confidence": 0.99,
                "words": words or [],
                **channel_extra,
            }]
        },
        "metadata": {"request_id": "uuid", "model_info": {"name": "nova-3"}},
    })


def test_interim_result_maps_to_nonfinal_transcript():
    events, last = parse_message(_results(is_final=False), -1.0)
    assert len(events) == 1
    t = events[0]
    assert isinstance(t, Transcript)
    assert t.is_final is False
    assert t.text == "hello world"
    assert t.start == 0.0 and t.end == 1.98
    assert last == -1.0  # no utterance end


def test_final_with_speech_final_emits_transcript_then_utterance_end():
    words = [{
        "word": "hello", "start": 0.4, "end": 0.9, "confidence": 0.98,
        "punctuated_word": "Hello,", "speaker": 0, "language": "en",
    }]
    events, last = parse_message(
        _results(is_final=True, speech_final=True, start=1.0, duration=2.0, words=words), -1.0
    )
    assert [type(e) for e in events] == [Transcript, UtteranceEnd]
    t, ue = events
    assert t.is_final is True
    assert t.words[0].w == "Hello,"  # punctuated form preferred
    assert t.words[0].speaker == 0
    assert t.words[0].lang == "en"
    assert ue.at == 3.0
    assert last == 3.0


def test_is_final_without_speech_final_is_not_an_utterance_boundary():
    # Deepgram docs: is_final can fire mid-utterance; only speech_final ends one.
    events, last = parse_message(_results(is_final=True, speech_final=False), -1.0)
    assert [type(e) for e in events] == [Transcript]
    assert last == -1.0


def test_utterance_end_message_suppressed_when_already_finalized():
    sentinel = json.dumps({"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": -1})
    events, last = parse_message(sentinel, 3.0)
    assert events == [] and last == 3.0

    stale = json.dumps({"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": 2.4})
    events, last = parse_message(stale, 3.0)
    assert events == [] and last == 3.0  # speech_final already covered this


def test_utterance_end_message_emitted_for_new_gap():
    raw = json.dumps({"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": 5.2})
    events, last = parse_message(raw, 3.0)
    assert [type(e) for e in events] == [UtteranceEnd]
    assert events[0].at == 5.2 and last == 5.2


def test_speech_started_and_metadata():
    events, _ = parse_message(json.dumps({"type": "SpeechStarted", "channel": [0, 1],
                                          "timestamp": 0.42}), -1.0)
    assert isinstance(events[0], SpeechStarted) and events[0].at == 0.42

    events, _ = parse_message(json.dumps({"type": "Metadata", "request_id": "x",
                                          "duration": 12.3}), -1.0)
    assert events == []


def test_empty_transcript_results_are_dropped():
    events, _ = parse_message(_results(text=""), -1.0)
    assert events == []


def _config(model="nova-3", **kw):
    return STTConfig(model=model, encoding="linear16", sample_rate=16000, **kw)


def test_build_url_keyterm_routing_by_model_family():
    # nova-3 uses keyterm (plain, repeatable)
    url3 = build_url(_config(model="nova-3", keyterms=("Celebrex", "Zyrtec")))
    assert "keyterm=Celebrex" in url3 and "keyterm=Zyrtec" in url3
    assert "keywords=" not in url3
    # nova-2 uses legacy keywords word:boost
    url2 = build_url(_config(model="nova-2", keyterms=("Celebrex",)))
    assert "keywords=Celebrex%3A2" in url2
    assert "keyterm=" not in url2


def test_build_url_utterance_end_requires_interim():
    with_interim = build_url(_config(interim_results=True))
    assert "utterance_end_ms=1000" in with_interim and "vad_events=true" in with_interim
    without = build_url(_config(interim_results=False))
    assert "utterance_end_ms" not in without and "vad_events" not in without


def test_build_url_provider_params_passthrough():
    url = build_url(_config(provider_params={"endpointing": 300, "smart_format": "true"}))
    assert "endpointing=300" in url and "smart_format=true" in url
