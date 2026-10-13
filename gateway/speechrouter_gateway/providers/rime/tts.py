"""Rime TTS: POST https://users.rime.ai/v1/rime-tts (docs/providers/tts/rime.md).

- `Authorization: Bearer`; body {speaker, text (<=1000), modelId, lang?,
  samplingRate, timeScaleFactor?}; the FORMAT is the Accept header (audio/L16 =
  headerless pcm, audio/PCMU, audio/mpeg, audio/ogg;codecs=opus). Raw bytes.
- Models: coda (flagship), mistv3, mistv2. Billed per character.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://users.rime.ai"

CAPABILITIES = TTSCapabilities(
    default_voice="astra",
    formats=frozenset({"pcm", "mp3", "opus", "mulaw"}),
    sample_rates=frozenset({8000, 16000, 22050, 24000}),
    format_rates={"mulaw": frozenset({8000})},
    max_input_chars=1000,
    speed=True,
)

_ACCEPT = {"pcm": "audio/L16", "mp3": "audio/mpeg", "opus": "audio/ogg;codecs=opus",
           "mulaw": "audio/PCMU"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("rime", capabilities=CAPABILITIES)
def build(settings: Settings) -> "RimeTTS":
    if not settings.rime_api_key:
        raise ProviderNotConfigured("rime")
    return RimeTTS({"key": settings.rime_api_key,
                    "base": tts_base_url(settings, "rime", BASE)}, TRANSPORT)


class RimeTTS(HTTPStreamTTS, TTSProvider):
    name = "rime"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"speaker": config.voice, "text": text, "modelId": config.model}
        if config.format in {"pcm", "mulaw"}:
            body["samplingRate"] = config.sample_rate
        if config.language:
            body["lang"] = config.language
        if config.speed is not None:
            body["timeScaleFactor"] = round(1 / config.speed, 3)  # Rime: >1 is SLOWER
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/rime-tts",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}",
                            "Accept": _ACCEPT[config.format]},
                "json": body}
