"""AWS Transcribe fixtures: event-stream codec roundtrip, SigV4 URL shape,
TranscriptEvent parsing."""

import datetime
import json

from speechrouter_gateway.protocol import Transcript, UtteranceEnd
from speechrouter_gateway.providers.aws.adapter import (
    parse_transcript_payload,
    speaker_to_int,
)
from speechrouter_gateway.providers.aws.eventstream import (
    build_audio_event,
    build_message,
    decode_message,
)
from speechrouter_gateway.providers.aws.signer import presigned_url


def test_eventstream_roundtrip():
    payload = json.dumps({"Transcript": {"Results": []}}).encode()
    message = build_message(
        {":message-type": "event", ":event-type": "TranscriptEvent",
         ":content-type": "application/json"},
        payload,
    )
    headers, decoded = decode_message(message)
    assert headers[":event-type"] == "TranscriptEvent"
    assert json.loads(decoded) == {"Transcript": {"Results": []}}


def test_audio_event_headers_and_empty_eos():
    headers, payload = decode_message(build_audio_event(b"\x01\x02"))
    assert headers[":event-type"] == "AudioEvent"
    assert headers[":message-type"] == "event"
    assert payload == b"\x01\x02"
    _, empty = decode_message(build_audio_event(b""))
    assert empty == b""  # end-of-stream sentinel


def test_presigned_url_is_sorted_and_signed():
    url = presigned_url(
        access_key="AKIA123", secret_key="secret", region="us-east-1",
        sample_rate=16000, language_code="en-US", show_speaker_label=True,
        now=datetime.datetime(2026, 7, 27, 12, 0, 0, tzinfo=datetime.UTC),
    )
    assert url.startswith("wss://transcribestreaming.us-east-1.amazonaws.com:8443/")
    assert "X-Amz-Signature=" in url and "X-Amz-Expires=300" in url
    assert "show-speaker-label=true" in url and "language-code=en-US" in url
    query = url.split("?", 1)[1]
    names = [p.split("=")[0] for p in query.split("&")]
    assert names[:-1] == sorted(names[:-1])  # canonical order (signature appended last)


def test_transcript_event_parsing_partial_final_and_punctuation():
    payload = {
        "Transcript": {"Results": [{
            "ResultId": "r1", "StartTime": 0.0, "EndTime": 1.9, "IsPartial": False,
            "Alternatives": [{
                "Transcript": "Hello world.",
                "Items": [
                    {"Type": "pronunciation", "Content": "Hello", "StartTime": 0.1,
                     "EndTime": 0.5, "Confidence": 0.99, "Speaker": "spk_0"},
                    {"Type": "pronunciation", "Content": "world", "StartTime": 0.6,
                     "EndTime": 1.0, "Confidence": 0.97, "Speaker": "spk_1"},
                    {"Type": "punctuation", "Content": "."},
                ],
            }],
        }]}
    }
    events = parse_transcript_payload(payload)
    assert [type(e) for e in events] == [Transcript, UtteranceEnd]
    t = events[0]
    assert t.is_final is True
    assert [w.w for w in t.words] == ["Hello", "world."]
    assert t.words[0].speaker == 0 and t.words[1].speaker == 1
    assert events[1].at == 1.9

    partial = {
        "Transcript": {"Results": [{
            "ResultId": "r2", "IsPartial": True, "StartTime": 2.0, "EndTime": 2.4,
            "Alternatives": [{"Transcript": "How", "Items": []}],
        }]}
    }
    events = parse_transcript_payload(partial)
    assert len(events) == 1 and events[0].is_final is False  # no utterance end


def test_speaker_mapping():
    assert speaker_to_int("spk_3") == 3
    assert speaker_to_int("0") == 0
    assert speaker_to_int(None) is None
