"""Smallest.ai Lightning TTS: POST https://api.smallest.ai/waves/v1/tts
(docs/providers/tts/smallest.md).

- Bearer auth; body {text, voice_id, model, sample_rate, speed, language?,
  output_format: pcm|wav|mp3|ulaw|alaw}; raw audio bytes back.
- Models lightning_v3.1 / lightning_v3.1_pro. Rates 8/16/24/44.1 kHz; native ulaw.
- WS (/waves/v1/tts/live, context_id continuations) exists, but its cancel
  message is unverified, so /v1/speak segments over this endpoint.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.smallest.ai"

CAPABILITIES = TTSCapabilities(
    default_voice="sophie",
    formats=frozenset({"pcm", "mp3", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 24000, 44100}),
    max_input_chars=8000,
    speed=True,
)

_FORMAT = {"pcm": "pcm", "mp3": "mp3", "mulaw": "ulaw", "alaw": "alaw"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("smallest", capabilities=CAPABILITIES)
def build(settings: Settings) -> "SmallestTTS":
    if not settings.smallest_api_key:
        raise ProviderNotConfigured("smallest")
    return SmallestTTS({"key": settings.smallest_api_key,
                        "base": tts_base_url(settings, "smallest", BASE)}, TRANSPORT)


class SmallestTTS(HTTPStreamTTS, TTSProvider):
    name = "smallest"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"text": text, "voice_id": config.voice, "model": config.model,
                      "sample_rate": config.sample_rate,
                      "output_format": _FORMAT[config.format]}
        if config.speed is not None:
            body["speed"] = config.speed
        if config.language:
            body["language"] = config.language
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/waves/v1/tts",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": body}
