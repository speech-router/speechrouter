"""include_raw: raw provider payloads survive normalization end to end."""

import json

from speechrouter_gateway.protocol import Transcript
from speechrouter_gateway.providers import assemblyai, deepgram
from speechrouter_gateway.providers.openai_compat import parse_openai_response
from speechrouter_gateway.providers.soniox.adapter import _TokenState


def test_deepgram_attaches_raw_only_when_asked():
    msg = {"type": "Results", "start": 0.0, "duration": 1.0, "is_final": True,
           "channel": {"alternatives": [{"transcript": "hi", "words": []}]}}
    events, _ = deepgram.adapter.parse_message(json.dumps(msg), -1.0, include_raw=True)
    assert events[0].provider_raw == msg
    events, _ = deepgram.adapter.parse_message(json.dumps(msg), -1.0)
    assert events[0].provider_raw is None


def test_assemblyai_attaches_raw():
    msg = {"type": "Turn", "turn_order": 0, "end_of_turn": True, "turn_is_formatted": True,
           "transcript": "Hi.", "words": []}
    events = assemblyai.adapter.parse_message(json.dumps(msg), include_raw=True)
    assert events[0].provider_raw == msg


def test_soniox_state_attaches_triggering_payload():
    state = _TokenState(include_raw=True)
    payload = {"tokens": [{"text": "hi", "start_ms": 0, "end_ms": 300, "is_final": True},
                          {"text": "<end>", "is_final": True}]}
    events = state.process(payload)
    finals = [e for e in events if isinstance(e, Transcript) and e.is_final]
    assert finals[0].provider_raw == payload


def test_batch_verbose_json_carries_raw():
    from speechrouter_gateway.api.formatters import to_verbose_json

    payload = {"text": "hello", "duration": 1.0, "extra_vendor_field": {"x": 1}}
    transcript = parse_openai_response(payload, include_raw=True)
    body = to_verbose_json(transcript, "openai/whisper-1")
    assert body["provider_raw"]["extra_vendor_field"] == {"x": 1}


def test_session_normalize_preserves_provider_raw():
    from speechrouter_gateway.config import Settings
    from speechrouter_gateway.metering.emitter import LogUsageEmitter
    from speechrouter_gateway.providers.base import STTConfig
    from speechrouter_gateway.router.resolver import ResolvedAttempt
    from speechrouter_gateway.router.session import STTSession

    config = STTConfig(model="x", encoding="linear16", sample_rate=16000)
    session = STTSession(
        transport=None,  # type: ignore[arg-type] - _normalize only
        attempts=[ResolvedAttempt(slug="p/x", config=config, build=lambda: None)],  # type: ignore[arg-type]
        emitter=LogUsageEmitter(),
        key_id="k",
        settings=Settings(_env_file=None),
    )
    event = Transcript(type="transcript", is_final=True, text="hi", start=0.0, end=1.0,
                       provider_raw={"vendor": "payload"})
    out = session._normalize(event, offset=2.0)
    assert out is not None and out.provider_raw == {"vendor": "payload"}
    assert out.end == 3.0  # offset applied, raw untouched
