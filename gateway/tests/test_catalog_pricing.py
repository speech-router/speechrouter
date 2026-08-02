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
