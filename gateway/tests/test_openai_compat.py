"""OpenAI / Groq / Mistral batch + OpenAI realtime fixtures."""

import pytest

from speechrouter_gateway.protocol import SpeechStarted, Transcript, UtteranceEnd
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.mistral.batch import MistralSTTBatch
from speechrouter_gateway.providers.openai.adapter import build_session_update, parse_event
from speechrouter_gateway.providers.openai.batch import OpenAISTTBatch
from speechrouter_gateway.providers.openai_compat import filename_for, parse_openai_response


def test_verbose_json_parse():
    payload = {
        "task": "transcribe", "language": "en", "duration": 2.1,
        "text": "Hello world.",
        "words": [{"word": "Hello", "start": 0.1, "end": 0.5},
                  {"word": "world.", "start": 0.6, "end": 1.0}],
    }
    t = parse_openai_response(payload)
    assert t.text == "Hello world." and t.end == 2.1 and t.lang == "en"
    assert [w.w for w in t.words] == ["Hello", "world."]


def test_plain_json_parse_and_filename():
    t = parse_openai_response({"text": "hi"})
    assert t.text == "hi" and t.words is None and t.end is None
    assert filename_for("audio/mpeg") == "audio.mp3"
    assert filename_for("application/octet-stream") == "audio.wav"


def test_openai_verbose_matrix():
    batch = OpenAISTTBatch("k")
    assert batch.wants_verbose(_config("whisper-1")) is True
    assert batch.wants_verbose(_config("gpt-4o-transcribe")) is False


def test_mistral_extras():
    batch = MistralSTTBatch("k")
    extra = batch.extra_form(_config("voxtral-mini-latest", diarization=True,
                                     keyterms=("Datasette", "SQLite")))
    assert extra["diarize"] == "true"
    assert extra["context_bias"] == "Datasette,SQLite"


def _config(model, **kw):
    return STTConfig(model=model, encoding="linear16", sample_rate=24000, **kw)


# ---- realtime ----

def test_session_update_nested_shape_and_vad_rules():
    native = build_session_update(_config("gpt-realtime-whisper", language="en"))
    session = native["session"]
    assert session["type"] == "transcription"
    assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert session["audio"]["input"]["transcription"]["model"] == "gpt-realtime-whisper"
    assert "turn_detection" not in session  # natively streaming: omit VAD

    vad = build_session_update(_config("gpt-4o-transcribe"))
    assert vad["session"]["turn_detection"] == {"type": "server_vad"}


def test_delta_accumulation_and_completed():
    accumulator: dict[str, str] = {}
    events = parse_event({"type": "conversation.item.input_audio_transcription.delta",
                          "item_id": "i1", "delta": "Hel"}, accumulator)
    assert events[0].is_final is False and events[0].text == "Hel"
    events = parse_event({"type": "conversation.item.input_audio_transcription.delta",
                          "item_id": "i1", "delta": "lo"}, accumulator)
    assert events[0].text == "Hello"  # accumulated hypothesis, not fragment
    events = parse_event({"type": "conversation.item.input_audio_transcription.completed",
                          "item_id": "i1", "transcript": "Hello."}, accumulator)
    assert isinstance(events[0], Transcript) and events[0].is_final is True
    assert events[0].text == "Hello."
    assert accumulator == {}  # item cleared


def test_vad_events_and_errors():
    accumulator: dict[str, str] = {}
    started = parse_event({"type": "input_audio_buffer.speech_started",
                           "audio_start_ms": 420}, accumulator)
    assert isinstance(started[0], SpeechStarted) and started[0].at == 0.42
    stopped = parse_event({"type": "input_audio_buffer.speech_stopped",
                           "audio_end_ms": 2395}, accumulator)
    assert isinstance(stopped[0], UtteranceEnd) and stopped[0].at == 2.395

    with pytest.raises(ProviderStreamError) as err:
        parse_event({"type": "error",
                     "error": {"code": "invalid_request_error", "message": "bad"}}, accumulator)
    assert err.value.recoverable is False
