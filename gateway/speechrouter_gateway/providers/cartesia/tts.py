"""Cartesia TTS: POST /tts/bytes (docs/providers/tts/cartesia.md).

- `Authorization: Bearer` + required `Cartesia-Version` header.
- Body {model_id, transcript, voice:{mode:id, id}, output_format{container,
  encoding, sample_rate}, language?, generation_config{speed}}; raw bytes back.
- Containers raw/wav/mp3; encodings pcm_s16le / pcm_mulaw / pcm_alaw at
  8k-48k. Billed in credits, 1 credit = 1 character.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.cartesia.ai"
API_VERSION = "2026-08-14"
RATES = frozenset({8000, 16000, 22050, 24000, 44100, 48000})

CAPABILITIES = TTSCapabilities(
    default_voice="db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",  # Skylar
    formats=frozenset({"pcm", "mp3", "mulaw", "alaw"}),
    sample_rates=RATES,
    max_input_chars=5000,
    speed=True,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("cartesia", capabilities=CAPABILITIES)
def build(settings: Settings) -> "CartesiaTTS":
    if not settings.cartesia_api_key:
        raise ProviderNotConfigured("cartesia")
    return CartesiaTTS({"key": settings.cartesia_api_key,
                        "base": tts_base_url(settings, "cartesia", BASE)}, TRANSPORT)


def output_format(fmt: str, rate: int) -> dict:
    if fmt == "mp3":
        return {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}
    encoding = {"pcm": "pcm_s16le", "mulaw": "pcm_mulaw", "alaw": "pcm_alaw"}[fmt]
    return {"container": "raw", "encoding": encoding, "sample_rate": rate}


class CartesiaTTS(HTTPStreamTTS, TTSProvider):
    name = "cartesia"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {
            "model_id": config.model,
            "transcript": text,
            "voice": {"mode": "id", "id": config.voice},
            "output_format": output_format(config.format, config.sample_rate),
        }
        if config.language:
            body["language"] = config.language
        if config.speed is not None:
            body["generation_config"] = {"speed": config.speed}
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {
            "url": f"{self.credentials['base']}/tts/bytes",
            "headers": {"Authorization": f"Bearer {self.credentials['key']}",
                        "Cartesia-Version": API_VERSION},
            "json": body,
        }
