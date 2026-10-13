"""ElevenLabs TTS: POST /v1/text-to-speech/{voice_id}/stream (docs/providers/tts/elevenlabs.md).

- `xi-api-key` header; output format is a QUERY param (`pcm_24000`,
  `mp3_44100_128`, `opus_48000_64`, `ulaw_8000`, `alaw_8000`).
- Body {text, model_id, language_code?, voice_settings{speed}}; raw audio
  bytes stream back. Billed per input character.
- WS input streaming (/stream-input) exists; /v1/speak currently uses the
  gateway segmenter over this HTTP endpoint.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.elevenlabs.io"
PCM_RATES = frozenset({8000, 16000, 22050, 24000, 44100, 48000})

CAPABILITIES = TTSCapabilities(
    default_voice="JBFqnCBsd6RMkjVDRZzb",  # George (official quickstart)
    formats=frozenset({"pcm", "mp3", "opus", "mulaw", "alaw"}),
    sample_rates=PCM_RATES,
    format_rates={"mulaw": frozenset({8000}), "alaw": frozenset({8000})},
    max_input_chars=5000,
    speed=True,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("elevenlabs", capabilities=CAPABILITIES)
def build(settings: Settings) -> "ElevenLabsTTS":
    if not settings.elevenlabs_api_key:
        raise ProviderNotConfigured("elevenlabs")
    return ElevenLabsTTS({"key": settings.elevenlabs_api_key,
                          "base": tts_base_url(settings, "elevenlabs", BASE)}, TRANSPORT)


def output_format(fmt: str, rate: int) -> str:
    return {
        "pcm": f"pcm_{rate}",
        "mp3": "mp3_44100_128",
        "opus": "opus_48000_64",
        "mulaw": "ulaw_8000",
        "alaw": "alaw_8000",
    }[fmt]


class ElevenLabsTTS(HTTPStreamTTS, TTSProvider):
    name = "elevenlabs"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"text": text, "model_id": config.model}
        if config.language:
            body["language_code"] = config.language
        if config.speed is not None:
            body["voice_settings"] = {"speed": config.speed}
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {
            "url": f"{self.credentials['base']}/v1/text-to-speech/{config.voice}/stream",
            "params": {"output_format": output_format(config.format, config.sample_rate)},
            "headers": {"xi-api-key": self.credentials["key"]},
            "json": body,
        }
