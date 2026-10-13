"""Together AI Kokoro TTS — the cheap open-weight tier (docs/providers/tts/together.md).

- POST https://api.together.ai/v1/audio/speech, Bearer; body {model:
  "hexgrad/Kokoro-82M", input, voice, response_format: wav,
  response_encoding: pcm_s16le, sample_rate: 24000, language?}.
- Non-streaming WAV is used: the docs show two conflicting SSE chunk shapes
  (UNVERIFIED which is live). The header is stripped -> raw pcm.
- Kokoro renders 24 kHz only; 8 kHz G.711 is decimated by the gateway.
- Together's standard ToS forbids medical information: non-PHI traffic only.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS, strip_wav_header
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.together.ai"
_MODELS = {"kokoro-82m": "hexgrad/Kokoro-82M"}

CAPABILITIES = TTSCapabilities(
    default_voice="af_heart",
    formats=frozenset({"pcm"}),
    sample_rates=frozenset({24000}),
    max_input_chars=4096,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("together", capabilities=CAPABILITIES)
def build(settings: Settings) -> "TogetherTTS":
    if not settings.together_api_key:
        raise ProviderNotConfigured("together")
    return TogetherTTS({"key": settings.together_api_key,
                        "base": tts_base_url(settings, "together", BASE)}, TRANSPORT)


class TogetherTTS(HTTPStreamTTS, TTSProvider):
    name = "together"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"model": _MODELS.get(config.model, config.model), "input": text,
                      "voice": config.voice, "response_format": "wav",
                      "response_encoding": "pcm_s16le", "sample_rate": 24000}
        if config.language:
            body["language"] = config.language
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/audio/speech",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": body}

    def strip_header(self, chunk, first):
        return strip_wav_header(chunk, first)
