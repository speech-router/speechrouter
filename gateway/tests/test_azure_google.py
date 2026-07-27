"""Azure + Google pure-helper fixtures (SDKs not required)."""

import json
from datetime import timedelta
from types import SimpleNamespace

from speechrouter_gateway.protocol import SpeechStarted, Transcript, UtteranceEnd
from speechrouter_gateway.providers.azure.adapter import (
    parse_detailed_json,
    speaker_to_int,
    ticks_to_seconds,
)
from speechrouter_gateway.providers.google.adapter import (
    endpoint_for,
    location_for,
    parse_response,
)


def test_azure_ticks_and_speakers():
    assert ticks_to_seconds(10_000_000) == 1.0
    assert ticks_to_seconds(5_000_000) == 0.5
    assert speaker_to_int("Guest-1") == 1
    assert speaker_to_int("Unknown") is None
    assert speaker_to_int(None) is None


def test_azure_detailed_json_parse():
    raw = json.dumps({
        "DisplayText": "Hello world.",
        "Offset": 10_000_000, "Duration": 20_000_000,
        "NBest": [{
            "Display": "Hello world.", "Confidence": 0.95,
            "Words": [
                {"Word": "hello", "Offset": 11_000_000, "Duration": 4_000_000},
                {"Word": "world", "Offset": 16_000_000, "Duration": 5_000_000},
            ],
        }],
    })
    t = parse_detailed_json(raw, speaker_id="Guest-2")
    assert t.is_final is True
    assert t.text == "Hello world."
    assert t.start == 1.0 and t.end == 3.0  # ticks -> seconds
    assert t.words[0].start == 1.1 and t.words[0].end == 1.5
    assert t.words[0].speaker == 2

    assert parse_detailed_json("not json") is None
    assert parse_detailed_json(json.dumps({"NBest": [{"Display": " "}]})) is None


def test_google_locations_and_endpoints():
    assert location_for("chirp_3") == "us"
    assert location_for("chirp_2") == "us-central1"
    assert location_for("latest_long") == "global"
    assert endpoint_for("us") == "us-speech.googleapis.com"
    assert endpoint_for("global") == "speech.googleapis.com"


def _google_response(**kw):
    defaults = dict(speech_event_type="", speech_event_offset=None, results=[])
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_google_response_parsing_with_rotation_offset():
    response = _google_response(results=[SimpleNamespace(
        is_final=True,
        result_end_offset=timedelta(seconds=2.5),
        language_code="en-US",
        alternatives=[SimpleNamespace(
            transcript="hello world",
            words=[SimpleNamespace(word="hello", start_offset=timedelta(seconds=0.1),
                                   end_offset=timedelta(seconds=0.5), confidence=0.9)],
        )],
    )])
    events = parse_response(response, offset=300.0)  # after one rotation
    t = events[0]
    assert isinstance(t, Transcript) and t.is_final is True
    assert t.end == 302.5  # rotation offset applied
    assert t.words[0].start == 300.1


def test_google_vad_events():
    begin = parse_response(_google_response(
        speech_event_type="SPEECH_ACTIVITY_BEGIN",
        speech_event_offset=timedelta(seconds=1.2)), offset=0.0)
    assert isinstance(begin[0], SpeechStarted) and begin[0].at == 1.2
    end = parse_response(_google_response(
        speech_event_type="SPEECH_ACTIVITY_END",
        speech_event_offset=timedelta(seconds=4.0)), offset=10.0)
    assert isinstance(end[0], UtteranceEnd) and end[0].at == 14.0
