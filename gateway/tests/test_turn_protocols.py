"""Deepgram Flux + Cartesia Turns fixtures — shapes from docs/providers/*.md."""

import json

import pytest

from speechrouter_gateway.config import Settings
from speechrouter_gateway.protocol import SpeechStarted, Transcript, UtteranceEnd
from speechrouter_gateway.providers.base import ProviderStreamError, STTConfig
from speechrouter_gateway.providers.cartesia import turns as cartesia_turns
from speechrouter_gateway.providers.deepgram import flux


def _turn_info(event, transcript="", words=None, start=0.0, end=1.5, **extra):
    return json.dumps({
        "type": "TurnInfo", "request_id": "uuid", "sequence_id": 1,
        "event": event, "turn_index": 0,
        "audio_window_start": start, "audio_window_end": end,
        "transcript": transcript, "words": words or [],
        "end_of_turn_confidence": 0.8, **extra,
    })


def test_flux_update_is_interim_and_end_of_turn_is_final():
    words = [{"word": "hello", "confidence": 0.95, "start": 0.0, "end": 0.5}]
    events = flux.parse_message(_turn_info("Update", "hello", words))
    assert len(events) == 1 and events[0].is_final is False
    assert events[0].words[0].w == "hello"

    events = flux.parse_message(_turn_info("EndOfTurn", "hello world", words, end=1.5))
    assert [type(e) for e in events] == [Transcript, UtteranceEnd]
    assert events[0].is_final is True and events[0].end == 1.5
    assert events[1].at == 1.5


def test_flux_start_of_turn_and_eager_events():
    events = flux.parse_message(_turn_info("StartOfTurn", start=0.42))
    assert isinstance(events[0], SpeechStarted) and events[0].at == 0.42
    # eager semantics deliberately dropped in v1
    assert flux.parse_message(_turn_info("EagerEndOfTurn", "hi")) == []
    assert flux.parse_message(_turn_info("TurnResumed")) == []
    assert flux.parse_message(json.dumps({"type": "Connected", "request_id": "x",
                                          "sequence_id": 0})) == []


def test_flux_error_and_url():
    with pytest.raises(ProviderStreamError):
        flux.parse_message(json.dumps({"type": "Error", "code": "X", "description": "boom",
                                       "sequence_id": 9}))
    url = flux.build_url(STTConfig(model="flux-general-en", encoding="linear16",
                                   sample_rate=16000, keyterms=("Vercel",),
                                   provider_params={"eot_threshold": 0.7}))
    assert url.startswith("wss://api.deepgram.com/v2/listen?")
    assert "model=flux-general-en" in url and "keyterm=Vercel" in url
    assert "eot_threshold=0.7" in url and "interim_results" not in url


def test_cartesia_turns_lifecycle_with_audio_clock():
    start = cartesia_turns.parse_message(json.dumps({"type": "turn.start"}), audio_clock=1.2)
    assert isinstance(start[0], SpeechStarted) and start[0].at == 1.2

    update = cartesia_turns.parse_message(
        json.dumps({"type": "turn.update", "transcript": "Hey can you"}), 2.0)
    assert update[0].is_final is False and update[0].text == "Hey can you"

    end = cartesia_turns.parse_message(
        json.dumps({"type": "turn.end", "transcript": "Hey, can you help?"}), 3.4)
    assert [type(e) for e in end] == [Transcript, UtteranceEnd]
    assert end[0].is_final is True and end[1].at == 3.4

    assert cartesia_turns.parse_message(json.dumps({"type": "turn.eager_end",
                                                    "transcript": "x"}), 1.0) == []
    assert cartesia_turns.parse_message(json.dumps({"type": "turn.resume"}), 1.0) == []
    assert cartesia_turns.parse_message(json.dumps({"type": "connected"}), 0.0) == []


def test_cartesia_turns_url_pins_version_and_thresholds():
    url = cartesia_turns.build_url(STTConfig(
        model="ink-2", encoding="linear16", sample_rate=16000, keyterms=("Vercel",),
        provider_params={"turn_eager_end_threshold": 0.4}))
    assert "cartesia_version=2026-03-01" in url
    assert "turn_eager_end_threshold=0.4" in url and "keyterm=Vercel" in url


async def test_dispatch_routes_by_model():
    from speechrouter_gateway.providers.cartesia.turns import CartesiaTurnsStream
    from speechrouter_gateway.providers.deepgram.flux import DeepgramFluxStream
    from speechrouter_gateway.providers.registry import stt_stream_provider

    settings = Settings(_env_file=None, deepgram_api_key="k", cartesia_api_key="k")

    deepgram = stt_stream_provider("deepgram").build(settings)
    impl, config = deepgram._chooser(STTConfig(model="flux-general-en", encoding="linear16",
                                               sample_rate=16000))
    assert isinstance(impl, DeepgramFluxStream) and config.model == "flux-general-en"

    cartesia = stt_stream_provider("cartesia").build(settings)
    impl, config = cartesia._chooser(STTConfig(model="ink-2-turns", encoding="linear16",
                                               sample_rate=16000))
    assert isinstance(impl, CartesiaTurnsStream)
    assert config.model == "ink-2"  # slug suffix stripped for the provider
