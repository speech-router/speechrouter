"""Pricing v2 invariants: native units authored, legacy field derived."""

from speechrouter_gateway.providers.base import BillingBasis
from speechrouter_gateway.router.catalog import Catalog

RATE_FIELDS = {
    "per_audio_second_usd": 1,
    "per_audio_minute_usd": 60,
    "per_audio_hour_usd": 3600,
    "per_session_hour_usd": 3600,
}


def test_every_model_has_exactly_one_native_rate_and_derived_legacy():
    catalog = Catalog.load()
    assert catalog.all(), "catalog must not be empty"
    for entry in catalog.all():
        if entry.get("kind", "stt") != "stt":
            continue  # unit-priced; see test_unit_priced_models_*
        pricing = entry.get("pricing", {})
        rates = [f for f in RATE_FIELDS if f in pricing]
        assert len(rates) == 1, f"{entry['slug']}: expected exactly one rate field, got {rates}"
        field = rates[0]
        # legacy consumers still see per_second_usd, derived not authored
        assert pricing["per_second_usd"] == pricing[field] / RATE_FIELDS[field], entry["slug"]


def test_session_billed_vendors_use_session_hour_units():
    catalog = Catalog.load()
    session_slugs = [
        e["slug"] for e in catalog.all() if "per_session_hour_usd" in e.get("pricing", {})
    ]
    assert any(s.startswith("soniox/stt-rt") for s in session_slugs)
    assert any(s.startswith("assemblyai/universal-3-5") for s in session_slugs)
    # batch models must never carry session pricing
    for entry in catalog.all():
        if "per_session_hour_usd" in entry.get("pricing", {}):
            assert "streaming" in entry.get("modes", []), entry["slug"]


def test_resolver_carries_billing_basis(monkeypatch):
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.router.resolver import StreamRequest, resolve_stream

    settings = Settings(
        keystore=KeyStoreKind.local, keys="k", _env_file=None,
        soniox_api_key="x", deepgram_api_key="x",
    )
    catalog = Catalog.load()
    request = StreamRequest(encoding="linear16", sample_rate=16000, channels=1)

    soniox = resolve_stream("soniox/stt-rt-v5", request, settings, catalog)
    assert soniox.billing_basis == BillingBasis.SESSION_TIME
    deepgram = resolve_stream("deepgram/nova-3", request, settings, catalog)
    assert deepgram.billing_basis == BillingBasis.AUDIO_TIME


def test_diarized_json_segments_become_speaker_words():
    from speechrouter_gateway.providers.openai_compat import parse_openai_response

    payload = {
        "text": "Hello there. General Kenobi.",
        "duration": 4.2,
        "segments": [
            {"text": " Hello there.", "speaker": "A", "start": 0.1, "end": 1.5},
            {"text": " General Kenobi.", "speaker": "B", "start": 2.0, "end": 4.0},
        ],
    }
    t = parse_openai_response(payload)
    assert t.text == "Hello there. General Kenobi."
    assert [w.speaker for w in t.words] == [0, 1]
    assert t.words[0].w == "Hello there."
    assert t.end == 4.2


def test_melia_selects_model_not_operating_point():
    from speechrouter_gateway.providers.base import STTConfig
    from speechrouter_gateway.providers.speechmatics.batch import build_job_config

    def make(model):
        return STTConfig(model=model, encoding="linear16", sample_rate=16000)

    cfg = build_job_config(make("melia-1"))["transcription_config"]
    assert cfg["model"] == "melia-1"
    assert cfg["language"] == "multi"
    assert "operating_point" not in cfg

    cfg = build_job_config(make("enhanced"))["transcription_config"]
    assert cfg["operating_point"] == "enhanced"
    assert "model" not in cfg


def test_diarize_model_resolves_with_diarization():
    from speechrouter_gateway.config import Settings
    from speechrouter_gateway.providers.openai.batch import OpenAISTTBatch
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import StreamRequest, resolve_batch

    resolved = resolve_batch(
        "openai/gpt-4o-transcribe-diarize",
        StreamRequest(diarization=True),
        Settings(openai_api_key="x"),
        Catalog.load(),
    )
    assert resolved.config.diarization
    assert OpenAISTTBatch("x").extra_form(resolved.config) == {
        "response_format": "diarized_json"
    }


def test_resolver_carries_list_price_for_metering():
    from speechrouter_gateway.config import Settings
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import StreamRequest, resolve_stream

    catalog = Catalog.load()
    r = resolve_stream("soniox/stt-rt-v5", StreamRequest(),
                       Settings(soniox_api_key="x"), catalog)
    assert abs(r.price_per_second_usd - 0.12 / 3600) < 1e-12

    r = resolve_stream("deepgram/nova-3", StreamRequest(),
                       Settings(deepgram_api_key="x"), catalog)
    assert abs(r.price_per_second_usd - 0.0048 / 60) < 1e-12


def test_elevenlabs_plain_commit_is_dropped_as_duplicate():
    from speechrouter_gateway.providers.elevenlabs.adapter import parse_message

    plain = {"message_type": "committed_transcript", "text": "hello there"}
    stamped = {
        "message_type": "committed_transcript_with_timestamps",
        "text": "hello there",
        "words": [
            {"type": "word", "text": "hello", "start": 0.1, "end": 0.4},
            {"type": "word", "text": "there", "start": 0.5, "end": 0.8},
        ],
    }
    import json
    assert parse_message(json.dumps(plain)) == []
    finals = parse_message(json.dumps(stamped))
    assert len(finals) == 1 and finals[0].is_final and finals[0].text == "hello there"


# ---- TTS / live (unit pricing, PLAN-tts-live.md §3.0) ----

def _schema_pricing_fields() -> set[str]:
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).parents[2] / "packages/spec/catalog.schema.json").read_text()
    )
    return set(schema["properties"]["pricing"]["properties"])


def test_unit_priced_models_have_known_rates_and_no_legacy_field():
    from speechrouter_gateway.router.catalog import UNIT_RATE_FIELDS

    allowed = {field for field, _ in UNIT_RATE_FIELDS.values()}
    schema_fields = _schema_pricing_fields()
    unit_models = [e for e in Catalog.load().all() if e["kind"] in {"tts", "live"}]
    assert {e["kind"] for e in unit_models} == {"tts", "live"}
    for entry in unit_models:
        pricing = entry["pricing"]
        assert pricing, entry["slug"]
        assert set(pricing) <= allowed, entry["slug"]
        assert set(pricing) <= schema_fields, entry["slug"]
        # never mispriced to a legacy seconds consumer
        assert "per_second_usd" not in pricing, entry["slug"]
        for step in entry.get("pricing_schedule", []):
            assert set(step["pricing"]) <= allowed, entry["slug"]


def test_live_models_declare_dialect():
    for entry in Catalog.load().all():
        if entry["kind"] == "live":
            assert entry["modes"] == ["live"]
            assert entry["dialect"] == {"openai": "openai-realtime",
                                        "gemini": "gemini-live"}[entry["provider"]]


def test_price_units_sums_components():
    from speechrouter_gateway.router.catalog import price_units

    entry = {"pricing": {"per_1m_text_input_tokens_usd": 0.60,
                         "per_1m_audio_output_tokens_usd": 12.00}}
    cost = price_units(entry, {"text_input_tokens": 1_000, "audio_output_tokens": 10_000,
                               "characters": 99})  # no per-char rate -> free
    assert abs(cost - (0.0006 + 0.12)) < 1e-12
    per_char = price_units({"pricing": {"per_character_usd": 0.000015}}, {"characters": 1000})
    assert abs(per_char - 0.015) < 1e-12


def test_pricing_schedule_switches_on_date():
    from datetime import UTC, datetime

    from speechrouter_gateway.router.catalog import effective_pricing

    entry = Catalog.load().find("gemini/gemini-3.8-flash-tts")
    assert entry is not None
    before = datetime(2026, 12, 31, 23, 59, tzinfo=UTC).timestamp()
    after = datetime(2027, 1, 1, 0, 0, tzinfo=UTC).timestamp()
    assert effective_pricing(entry, before)["per_1m_audio_output_tokens_usd"] == 9.00
    assert effective_pricing(entry, after)["per_1m_audio_output_tokens_usd"] == 18.00


def test_disabled_kinds_vanish():
    catalog = Catalog.load(disabled_kinds=frozenset({"tts", "live"}))
    assert catalog.find("openai/gpt-4o-mini-tts") is None
    assert catalog.find("openai/gpt-realtime-2.1") is None
    assert catalog.find("deepgram/nova-3") is not None
    assert all(e["kind"] == "stt" for e in catalog.public())


def test_tts_slug_is_not_transcription():
    import pytest

    from speechrouter_gateway.config import Settings
    from speechrouter_gateway.router.resolver import (
        ResolveError,
        StreamRequest,
        resolve_batch,
        resolve_stream,
    )

    settings = Settings(openai_api_key="x", _env_file=None)
    catalog = Catalog.load()
    with pytest.raises(ResolveError):
        resolve_stream("openai/gpt-4o-mini-tts", StreamRequest(), settings, catalog)
    with pytest.raises(ResolveError):
        resolve_batch("openai/tts-1", StreamRequest(), settings, catalog)
