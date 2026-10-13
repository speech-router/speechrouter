"""Groq TTS (Canopy Orpheus): POST /openai/v1/audio/speech (docs/providers/tts/groq.md).

- OpenAI-shaped, `Authorization: Bearer`; body {model, input (<=200 chars!),
  voice, response_format, sample_rate, speed}.
- Only `wav` is confirmed in Groq's docs, so the adapter always asks for wav
  and strips the header, yielding raw pcm at the requested rate.
- PlayAI TTS (playai-tts*) was shut down 2025-12-31. Slugs drop the
  `canopylabs/` prefix (slugs can't nest): groq/orpheus-v1-english ->
  canopylabs/orpheus-v1-english. Billed per input character.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS, strip_wav_header
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.groq.com/openai/v1"

CAPABILITIES = TTSCapabilities(
    default_voice="autumn",
    formats=frozenset({"pcm"}),
    sample_rates=frozenset({8000, 16000, 22050, 24000, 32000, 44100, 48000}),
    max_input_chars=200,
    speed=True,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("groq", capabilities=CAPABILITIES)
def build(settings: Settings) -> "GroqTTS":
    if not settings.groq_api_key:
        raise ProviderNotConfigured("groq")
    return GroqTTS({"key": settings.groq_api_key,
                    "base": tts_base_url(settings, "groq", BASE)}, TRANSPORT)


class GroqTTS(HTTPStreamTTS, TTSProvider):
    name = "groq"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"model": f"canopylabs/{config.model}", "input": text,
                      "voice": config.voice, "response_format": "wav",
                      "sample_rate": config.sample_rate}
        if config.speed is not None:
            body["speed"] = config.speed
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/audio/speech",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": body}

    def strip_header(self, chunk, first):
        return strip_wav_header(chunk, first)
