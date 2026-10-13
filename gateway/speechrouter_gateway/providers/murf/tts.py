"""Murf TTS (Falcon 2): POST https://global.api.murf.ai/v1/speech/stream
(docs/providers/tts/murf.md).

- `api-key` header (bad key -> 403); body {text, voiceId, model:"falcon-2",
  format, sampleRate, locale?, rate?}; chunked raw audio back.
- Formats PCM (16-bit mono; little-endian assumed, UNVERIFIED), MP3, FLAC,
  ULAW, ALAW, OGG; rates 8k/16k/24k/44.1k/48k. Gen2 is non-streaming only and
  not exposed. Billed per character.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://global.api.murf.ai"

CAPABILITIES = TTSCapabilities(
    default_voice="Natalie",
    formats=frozenset({"pcm", "mp3", "flac", "opus", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 24000, 44100, 48000}),
    max_input_chars=3000,
    speed=True,
)

_FORMAT = {"pcm": "PCM", "mp3": "MP3", "flac": "FLAC", "opus": "OGG", "mulaw": "ULAW",
           "alaw": "ALAW"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("murf", capabilities=CAPABILITIES)
def build(settings: Settings) -> "MurfTTS":
    if not settings.murf_api_key:
        raise ProviderNotConfigured("murf")
    return MurfTTS({"key": settings.murf_api_key,
                    "base": tts_base_url(settings, "murf", BASE)}, TRANSPORT)


class MurfTTS(HTTPStreamTTS, TTSProvider):
    name = "murf"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"text": text, "voiceId": config.voice, "model": config.model,
                      "format": _FORMAT[config.format], "sampleRate": config.sample_rate}
        if config.language:
            body["locale"] = config.language
        if config.speed is not None:
            body["rate"] = round((config.speed - 1) * 100)  # Murf rate: -50..50 percent
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/speech/stream",
                "headers": {"api-key": self.credentials["key"]}, "json": body}
