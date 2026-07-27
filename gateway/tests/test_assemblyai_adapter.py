"""AssemblyAI v3 fixtures — shapes from docs/providers/assemblyai.md."""

import json

import pytest

from speechrouter_gateway.protocol import SpeechStarted, Transcript, UtteranceEnd
from speechrouter_gateway.providers.assemblyai.adapter import (
    build_url,
    parse_message,
    speaker_to_int,
)
from speechrouter_gateway.providers.assemblyai.batch import build_job, parse_transcript
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig


def _turn(transcript, end_of_turn=False, formatted=False, words=None, **extra):
    return json.dumps({
        "type": "Turn", "turn_order": 0, "turn_is_formatted": formatted,
        "end_of_turn": end_of_turn, "transcript": transcript,
        "end_of_turn_confidence": 0.9, "utterance": transcript if end_of_turn else "",
        "words": words or [], **extra,
    })


WORDS = [
    {"start": 1216, "end": 1627, "text": "My", "confidence": 0.95, "word_is_final": True},
    {"start": 1700, "end": 2000, "text": "name", "confidence": 0.93, "word_is_final": True,
     "speaker": "B"},
]


def test_partial_turn_is_interim():
    events = parse_message(_turn("My name", words=WORDS))
    assert len(events) == 1
    t = events[0]
    assert isinstance(t, Transcript) and t.is_final is False
    assert t.words[0].start == 1.216 and t.words[0].end == 1.627  # ms -> s
    assert t.words[1].speaker == 1  # "B" -> 1


def test_unformatted_final_is_swallowed_formatted_final_emits():
    # format_turns=true doubles the final: unformatted first...
    assert parse_message(_turn("my name is sonny", end_of_turn=True, formatted=False)) == []
    # ...then formatted, which is THE final + utterance end
    events = parse_message(
        _turn("My name is Sonny.", end_of_turn=True, formatted=True, words=WORDS)
    )
    assert [type(e) for e in events] == [Transcript, UtteranceEnd]
    assert events[0].is_final is True
    assert events[1].at == 2.0


def test_speech_started_and_empty_turns():
    events = parse_message(json.dumps({"type": "SpeechStarted", "timestamp": 1216,
                                       "confidence": 0.98}))
    assert isinstance(events[0], SpeechStarted) and events[0].at == 1.216
    assert parse_message(_turn("")) == []
    assert parse_message(json.dumps({"type": "Begin", "id": "x", "expires_at": 1})) == []


def test_error_recoverability_by_code():
    with pytest.raises(ProviderStreamError) as expired:
        parse_message(json.dumps({"type": "Error", "error_code": 3008,
                                  "error": "Session Expired"}))
    assert expired.value.recoverable is True
    with pytest.raises(ProviderStreamError) as pacing:
        parse_message(json.dumps({"type": "Error", "error_code": 3007,
                                  "error": "chunk size"}))
    assert pacing.value.recoverable is False


def test_build_url_params():
    config = STTConfig(model="universal-3-5-pro", encoding="linear16", sample_rate=16000,
                       language="en", diarization=True, keyterms=("AssemblyAI",))
    url = build_url(config)
    assert "speech_model=universal-3-5-pro" in url
    assert "encoding=pcm_s16le" in url
    assert "format_turns=true" in url
    assert "speaker_labels=true" in url
    assert "language_codes=" in url and "keyterms_prompt=" in url


def test_speaker_letters_and_digits():
    assert speaker_to_int("A") == 0
    assert speaker_to_int("C") == 2
    assert speaker_to_int("3") == 3
    assert speaker_to_int(None) is None
    assert speaker_to_int("spk_x") is None


def test_batch_job_and_parse():
    config = STTConfig(model="universal", encoding="linear16", sample_rate=16000,
                       diarization=True)
    job = build_job("https://cdn/u", config)
    assert job["speaker_labels"] is True and job["language_detection"] is True

    payload = {
        "status": "completed", "text": "Hello there.", "language_code": "en",
        "words": [
            {"text": "Hello", "start": 100, "end": 480, "confidence": 0.99, "speaker": "A"},
            {"text": "there.", "start": 520, "end": 900, "confidence": 0.98, "speaker": "A"},
        ],
    }
    t = parse_transcript(payload)
    assert t.text == "Hello there."
    assert t.end == 0.9 and t.words[0].speaker == 0 and t.lang == "en"
