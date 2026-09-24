"""Azure fast-transcription fixtures — ms units, phrase/word shapes."""

from speechrouter_gateway.providers.azure.batch import build_definition, parse_response
from speechrouter_gateway.providers.base import STTConfig


def test_definition_shape():
    config = STTConfig(model="fast-transcription", encoding="linear16", sample_rate=16000,
                       language="en-US", diarization=True, keyterms=("Contoso",))
    definition = build_definition(config)
    assert definition["locales"] == ["en-US"]
    assert definition["diarization"] == {"enabled": True, "maxSpeakers": 10}
    assert definition["phraseList"]["phrases"] == ["Contoso"]


def test_parse_ms_units_and_speakers():
    payload = {
        "durationMilliseconds": 2500,
        "combinedPhrases": [{"channel": 0, "text": "Hello world. How are you?"}],
        "phrases": [
            {"channel": 0, "speaker": 1, "offsetMilliseconds": 100,
             "durationMilliseconds": 900, "text": "Hello world.", "locale": "en-US",
             "confidence": 0.95,
             "words": [
                 {"text": "Hello", "offsetMilliseconds": 100, "durationMilliseconds": 400},
                 {"text": "world.", "offsetMilliseconds": 550, "durationMilliseconds": 450},
             ]},
            {"channel": 0, "speaker": 2, "offsetMilliseconds": 1200,
             "durationMilliseconds": 1300, "text": "How are you?", "locale": "en-US",
             "confidence": 0.93,
             "words": [
                 {"text": "How", "offsetMilliseconds": 1200, "durationMilliseconds": 300},
             ]},
        ],
    }
    t = parse_response(payload)
    assert t.text == "Hello world. How are you?"
    assert t.end == 2.5
    assert t.lang == "en-US"
    assert t.words[0].start == 0.1 and t.words[0].end == 0.5  # ms -> s
    assert t.words[0].speaker == 1 and t.words[2].speaker == 2


# MAI-Transcribe: same endpoint, enhancedMode selects the model. Definitions
# mirror the wire examples in learn.microsoft.com .../speech-service/mai-transcribe.


def _mai(model, **kwargs):
    return STTConfig(model=model, encoding="linear16", sample_rate=16000, **kwargs)


def test_mai_2_definition_shape():
    definition = build_definition(_mai(
        "mai-transcribe-2", language="en-US", diarization=True, keyterms=("Contoso",),
    ))
    assert definition == {
        "enhancedMode": {
            "enabled": True,
            "model": "MAI-Transcribe-2",
            "modelOptions": {"timestamps": "word"},  # vendor default is "none"
        },
        "locales": ["en"],  # one bare code, not a locale
        "diarization": {"enabled": True},
        "phraseList": {"phrases": ["Contoso"]},
    }


def test_mai_auto_language_is_omitted():
    assert "locales" not in build_definition(_mai("mai-transcribe-2", language="auto"))
    assert build_definition(_mai("mai-transcribe-2", language="yue"))["locales"] == ["yue"]


def test_mai_1_5_uses_its_documented_spelling_and_never_diarizes():
    definition = build_definition(_mai("mai-transcribe-1.5", diarization=True))
    assert definition == {"enhancedMode": {"enabled": True, "model": "mai-transcribe-1.5"}}


def test_mai_provider_params_merge_but_cannot_swap_the_model():
    definition = build_definition(_mai("mai-transcribe-2", provider_params={
        "enhancedMode": {"model": "MAI-Transcribe-1.5",
                         "modelOptions": {"transcribeStyle": "clean"}},
    }))
    assert definition["enhancedMode"] == {
        "enabled": True,
        "model": "MAI-Transcribe-2",
        "modelOptions": {"timestamps": "word", "transcribeStyle": "clean"},
    }


def test_fast_transcription_cannot_be_turned_into_a_mai_request():
    definition = build_definition(STTConfig(
        model="fast-transcription", encoding="linear16", sample_rate=16000,
        provider_params={"enhancedMode": {"model": "MAI-Transcribe-2", "task": "transcribe"}},
    ))
    assert definition["enhancedMode"] == {"task": "transcribe"}


def test_fast_transcription_params_merge_into_diarization():
    definition = build_definition(STTConfig(
        model="fast-transcription", encoding="linear16", sample_rate=16000,
        diarization=True, provider_params={"diarization": {"maxSpeakers": 4}},
    ))
    assert definition["diarization"] == {"enabled": True, "maxSpeakers": 4}


def test_parse_mai_diarized_word_response():
    # response shape per the LLM Speech sample response; MAI returns the same
    # TranscribeResult (confidence is always 0 in enhanced mode)
    payload = {
        "durationMilliseconds": 4000,
        "combinedPhrases": [{"text": "Hi there. Hello."}],
        "phrases": [
            {"speaker": 1, "offsetMilliseconds": 80, "durationMilliseconds": 800,
             "text": "Hi there.", "locale": "en-us", "confidence": 0,
             "words": [
                 {"text": "Hi", "offsetMilliseconds": 80, "durationMilliseconds": 240},
                 {"text": "there.", "offsetMilliseconds": 320, "durationMilliseconds": 560},
             ]},
            {"speaker": 2, "offsetMilliseconds": 2000, "durationMilliseconds": 600,
             "text": "Hello.", "locale": "en-us", "confidence": 0,
             "words": [
                 {"text": "Hello.", "offsetMilliseconds": 2000, "durationMilliseconds": 600},
             ]},
        ],
    }
    t = parse_response(payload)
    assert t.text == "Hi there. Hello."
    assert t.end == 4.0
    assert t.lang == "en-us"
    assert [w.speaker for w in t.words] == [1, 1, 2]
    assert t.words[1].start == 0.32 and t.words[1].end == 0.88


def test_parse_mai_response_without_timestamps():
    # timestamps "none" / MAI-Transcribe-1.5: phrases carry no words
    payload = {
        "durationMilliseconds": 1500,
        "combinedPhrases": [{"text": "Bonjour."}],
        "phrases": [{"offsetMilliseconds": 0, "durationMilliseconds": 1500,
                     "text": "Bonjour.", "locale": "fr", "confidence": 0}],
    }
    t = parse_response(payload)
    assert t.text == "Bonjour."
    assert t.words is None
    assert t.end == 1.5 and t.lang == "fr"


def test_mai_models_resolve_through_the_azure_batch_provider():
    from speechrouter_gateway.config import KeyStoreKind, Settings
    from speechrouter_gateway.router.catalog import Catalog
    from speechrouter_gateway.router.resolver import StreamRequest, resolve_batch

    settings = Settings(
        keystore=KeyStoreKind.local, keys="k", _env_file=None,
        azure_speech_key="x", azure_speech_region="eastus",
    )
    catalog = Catalog.load()
    for slug, model in [("azure/mai-transcribe-2", "mai-transcribe-2"),
                        ("azure/mai-transcribe-1.5", "mai-transcribe-1.5")]:
        resolved = resolve_batch(slug, StreamRequest(), settings, catalog)
        assert resolved.config.model == model
    entry = catalog.find("azure/mai-transcribe-2")
    assert entry["pricing"]["per_audio_hour_usd"] == 0.1
    assert entry["capabilities"]["diarization"] is True
    assert catalog.find("azure/mai-transcribe-1.5")["capabilities"]["diarization"] is False
