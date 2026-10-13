"""Google Cloud Text-to-Speech: POST /v1/text:synthesize (docs/providers/tts/google.md).

- NOT streaming over REST: one JSON response with base64 `audioContent`, so
  time-to-first-byte is the whole synthesis. (StreamingSynthesize is gRPC.)
- Auth: API key in `x-goog-api-key` (whether Cloud TTS accepts API keys is
  UNVERIFIED in the docs read; verify with the live probe).
- Body {input:{text}, voice:{languageCode, name}, audioConfig{audioEncoding,
  sampleRateHertz, speakingRate}}. LINEAR16 carries a WAV header -> stripped.
- Slugs are voice tiers (google/standard, google/neural2, google/studio,
  google/chirp3-hd); the request's voice is the full name. Per character.
- Limit 5000 BYTES per request; the catalog caps at 4000 characters.
"""

import base64

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS, strip_wav_header
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://texttospeech.googleapis.com"

CAPABILITIES = TTSCapabilities(
    default_voice="en-US-Chirp3-HD-Kore",
    formats=frozenset({"pcm", "mp3", "opus", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 24000, 48000}),
    format_rates={"mulaw": frozenset({8000}), "alaw": frozenset({8000})},
    max_input_chars=4000,
    speed=True,
)

_ENCODING = {"pcm": "LINEAR16", "mp3": "MP3", "opus": "OGG_OPUS", "mulaw": "MULAW",
             "alaw": "ALAW"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("google", capabilities=CAPABILITIES)
def build(settings: Settings) -> "GoogleTTS":
    if not settings.google_tts_api_key:
        raise ProviderNotConfigured("google")
    return GoogleTTS({"key": settings.google_tts_api_key,
                      "base": tts_base_url(settings, "google", BASE)}, TRANSPORT)


class GoogleTTS(HTTPStreamTTS, TTSProvider):
    name = "google"
    capabilities = CAPABILITIES
    response_mode = "json"

    def build_request(self, text, config):
        language = config.language or "-".join(config.voice.split("-")[:2])
        audio: dict = {"audioEncoding": _ENCODING[config.format]}
        if config.format in {"pcm", "mulaw", "alaw"}:
            audio["sampleRateHertz"] = config.sample_rate
        if config.speed is not None:
            audio["speakingRate"] = config.speed
        body = {"input": {"text": text},
                "voice": {"languageCode": language, "name": config.voice},
                "audioConfig": audio}
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/text:synthesize",
                "headers": {"x-goog-api-key": self.credentials["key"]}, "json": body}

    def audio_from_event(self, event, state):
        data = event.get("audioContent")
        return base64.b64decode(data) if data else None

    def strip_header(self, chunk, first):
        return strip_wav_header(chunk, first)
