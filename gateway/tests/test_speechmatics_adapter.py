"""Speechmatics fixtures — shapes from docs/providers/speechmatics.md."""

import json

import pytest

from speechrouter_gateway.protocol import Transcript, UtteranceEnd
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.speechmatics.adapter import (
    build_start_recognition,
    parse_message,
    results_to_words,
    speaker_to_int,
)
from speechrouter_gateway.providers.speechmatics.batch import build_job_config, parse_json_v2

RESULTS = [
    {"type": "word", "start_time": 0.0, "end_time": 0.5,
     "alternatives": [{"content": "hello", "confidence": 0.93, "speaker": "S1"}]},
    {"type": "word", "start_time": 0.6, "end_time": 1.4,
     "alternatives": [{"content": "world", "confidence": 0.9, "speaker": "S1"}]},
    {"type": "punctuation", "start_time": 1.5, "end_time": 1.5, "is_eos": True,
     "attaches_to": "previous", "alternatives": [{"content": ".", "confidence": 1.0}]},
]


def test_results_to_words_glues_punctuation_and_maps_speakers():
    words = results_to_words(RESULTS)
    assert [w.w for w in words] == ["hello", "world."]
    assert words[0].speaker == 1
    assert words[1].end == 1.4


def test_add_transcript_is_final_and_partial_is_not():
    final_raw = json.dumps({
        "message": "AddTranscript", "format": "2.1",
        "metadata": {"start_time": 0.0, "end_time": 1.5, "transcript": "Hello world."},
        "results": RESULTS,
    })
    kind, events = parse_message(final_raw)
    assert kind == "events"
    t = events[0]
    assert isinstance(t, Transcript) and t.is_final is True
    assert t.text == "Hello world." and t.end == 1.5

    partial = json.dumps({
        "message": "AddPartialTranscript",
        "metadata": {"start_time": 1.5, "end_time": 1.9, "transcript": "How"},
        "results": [],
    })
    kind, events = parse_message(partial)
    assert events[0].is_final is False


def test_control_messages():
    assert parse_message(json.dumps({"message": "AudioAdded", "seq_no": 12})) == ("ack", 12)
    assert parse_message(json.dumps({"message": "RecognitionStarted", "id": "s"}))[0] == "started"
    assert parse_message(json.dumps({"message": "EndOfTranscript"}))[0] == "end"
    kind, events = parse_message(json.dumps(
        {"message": "EndOfUtterance", "metadata": {"start_time": 10.5, "end_time": 10.5}}
    ))
    assert isinstance(events[0], UtteranceEnd) and events[0].at == 10.5
    assert parse_message(json.dumps({"message": "Warning", "type": "duration_limit_exceeded",
                                     "reason": "x"})) == ("events", [])


def test_error_recoverability():
    with pytest.raises(ProviderStreamError) as quota:
        parse_message(json.dumps({"message": "Error", "type": "quota_exceeded", "reason": "r"}))
    assert quota.value.recoverable is True
    with pytest.raises(ProviderStreamError) as auth:
        parse_message(json.dumps({"message": "Error", "type": "not_authorised", "reason": "r"}))
    assert auth.value.recoverable is False


def test_start_recognition_shape():
    config = STTConfig(model="enhanced", encoding="linear16", sample_rate=16000,
                       language="en", diarization=True, keyterms=("gnocchi",),
                       provider_params={"max_delay": 1.5})
    msg = build_start_recognition(config)
    assert msg["message"] == "StartRecognition"
    assert msg["audio_format"] == {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000}
    tc = msg["transcription_config"]
    assert tc["model"] == "enhanced" and tc["diarization"] == "speaker"
    assert tc["additional_vocab"] == [{"content": "gnocchi"}]
    assert tc["max_delay"] == 1.5
    assert tc["conversation_config"]["end_of_utterance_silence_trigger"] < tc["max_delay"] + 3


def test_speaker_mapping():
    assert speaker_to_int("S1") == 1
    assert speaker_to_int("S12") == 12
    assert speaker_to_int("UU") is None
    assert speaker_to_int(None) is None


def test_batch_config_and_json_v2_parse():
    config = STTConfig(model="enhanced", encoding="linear16", sample_rate=16000)
    job = build_job_config(config)
    assert job["type"] == "transcription"
    assert job["transcription_config"]["operating_point"] == "enhanced"

    t = parse_json_v2({"format": "2.9", "results": RESULTS})
    assert t.text == "hello world."
    assert t.end == 1.4
