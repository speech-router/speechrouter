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
