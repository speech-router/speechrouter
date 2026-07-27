"""Cartesia + ElevenLabs fixtures — shapes from docs/providers/*.md."""

import json

import pytest

from speechrouter_gateway.protocol import Transcript
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.cartesia import adapter as cartesia
from speechrouter_gateway.providers.cartesia.batch import parse_response as cartesia_batch_parse
from speechrouter_gateway.providers.elevenlabs import adapter as elevenlabs
from speechrouter_gateway.providers.elevenlabs.batch import parse_response as el_batch_parse

# ---- Cartesia ----

def test_cartesia_transcript_delta_and_acks():
    raw = json.dumps({
        "type": "transcript", "is_final": True, "request_id": "r1",
        "text": "How are you doing today?", "duration": 2.5,
        "words": [{"word": "How", "start": 0.0, "end": 0.12},
                  {"word": "are", "start": 0.15, "end": 0.3}],
    })
    kind, events = cartesia.parse_message(raw)
    assert kind == "events"
    t = events[0]
    assert t.is_final is True and t.words[0].w == "How"

    assert cartesia.parse_message(json.dumps({"type": "flush_done", "request_id": "r"}))[0] == \
        "flush_done"
    assert cartesia.parse_message(json.dumps({"type": "done", "request_id": "r"}))[0] == "done"


def test_cartesia_error_recoverability():
    with pytest.raises(ProviderStreamError) as client_err:
        cartesia.parse_message(json.dumps({"type": "error", "error_code": "model_not_found",
                                           "message": "x", "status_code": 400}))
    assert client_err.value.recoverable is False
    with pytest.raises(ProviderStreamError) as server_err:
        cartesia.parse_message(json.dumps({"type": "error", "error_code": "internal",
                                           "message": "x", "status_code": 503}))
    assert server_err.value.recoverable is True


def test_cartesia_url_keyterms_only_for_ink2():
    ink2 = cartesia.build_url(STTConfig(model="ink-2", encoding="linear16",
                                        sample_rate=16000, keyterms=("Vercel",)))
    assert "keyterm=Vercel" in ink2 and "cartesia_version=2026-03-01" in ink2
    whisper = cartesia.build_url(STTConfig(model="ink-whisper", encoding="linear16",
                                           sample_rate=16000, keyterms=("Vercel",)))
    assert "keyterm=" not in whisper


def test_cartesia_batch_parse():
    t = cartesia_batch_parse({"type": "transcript", "text": "hi", "duration": 1.2,
                              "language": "en",
                              "words": [{"word": "hi", "start": 0.0, "end": 0.4}]})
    assert t.end == 1.2 and t.lang == "en"


# ---- ElevenLabs ----

def test_elevenlabs_partial_and_committed_with_timestamps():
    partial = elevenlabs.parse_message(json.dumps(
        {"message_type": "partial_transcript", "text": "hel"}
    ))
    assert partial[0].is_final is False

    committed = elevenlabs.parse_message(json.dumps({
        "message_type": "committed_transcript_with_timestamps",
        "text": "Hello world", "language_code": "en",
        "words": [
            {"text": "Hello", "start": 0.1, "end": 0.5, "type": "word",
             "speaker_id": "speaker_1"},
            {"text": " ", "start": 0.5, "end": 0.6, "type": "spacing"},
            {"text": "world", "start": 0.6, "end": 1.0, "type": "word",
             "speaker_id": "speaker_1"},
            {"text": "(laughs)", "start": 1.0, "end": 1.4, "type": "audio_event"},
        ],
    }))
    t = committed[0]
    assert isinstance(t, Transcript) and t.is_final is True
    # spacing + audio_event filtered from words
    assert [w.w for w in t.words] == ["Hello", "world"]
    assert t.words[0].speaker == 1
    assert t.lang == "en"


def test_elevenlabs_error_enum():
    with pytest.raises(ProviderStreamError) as throttled:
        elevenlabs.parse_message(json.dumps({"message_type": "commit_throttled",
                                             "error": "slow down"}))
    assert throttled.value.recoverable is True
    with pytest.raises(ProviderStreamError) as auth:
        elevenlabs.parse_message(json.dumps({"message_type": "auth_error", "error": "bad"}))
    assert auth.value.recoverable is False
    assert elevenlabs.parse_message(json.dumps({"message_type": "session_started",
                                                "session_id": "s", "config": {}})) == []


def test_elevenlabs_audio_format_and_url():
    assert elevenlabs.audio_format_for("linear16", 16000) == "pcm_16000"
    assert elevenlabs.audio_format_for("mulaw", 8000) == "ulaw_8000"
    url = elevenlabs.build_url(STTConfig(model="scribe_v2_realtime", encoding="linear16",
                                         sample_rate=16000, language="en"))
    assert "model_id=scribe_v2_realtime" in url
    assert "commit_strategy=vad" in url and "language_code=en" in url


def test_elevenlabs_batch_parse():
    t = el_batch_parse({
        "language_code": "en", "text": "Hi there",
        "words": [
            {"text": "Hi", "start": 0.0, "end": 0.3, "type": "word", "speaker_id": "speaker_0"},
            {"text": "there", "start": 0.4, "end": 0.8, "type": "word",
             "speaker_id": "speaker_0"},
        ],
    })
    assert t.text == "Hi there" and t.words[0].speaker == 0 and t.end == 0.8
