"""Fish Audio TTS: POST https://api.fish.audio/v1/tts (docs/providers/tts/fishaudio.md).

- `Authorization: Bearer`; the MODEL rides a `model` header, not the body.
- JSON body {text, reference_id (voice), format, sample_rate, prosody{speed},
  latency}; chunked raw audio back.
- Formats pcm/wav (8-44.1k), mp3 (44.1k), opus (48k); no G.711 (gateway
  encodes it from pcm).
- **Billed per UTF-8 BYTE of input**, not per character: units.utf8_bytes
  (catalog per_utf8_byte_usd). ASCII = 1 byte, CJK ~3.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.fish.audio"

CAPABILITIES = TTSCapabilities(
    default_voice="9a9cf47702da476aa4629e2506d4a857",  # from Fish's own examples
    formats=frozenset({"pcm", "mp3", "opus"}),
    sample_rates=frozenset({8000, 16000, 24000, 32000, 44100}),
    max_input_chars=4096,
    speed=True,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("fishaudio", capabilities=CAPABILITIES)
def build(settings: Settings) -> "FishAudioTTS":
    if not settings.fishaudio_api_key:
        raise ProviderNotConfigured("fishaudio")
    return FishAudioTTS({"key": settings.fishaudio_api_key,
                         "base": tts_base_url(settings, "fishaudio", BASE)}, TRANSPORT)


class FishAudioTTS(HTTPStreamTTS, TTSProvider):
    name = "fishaudio"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"text": text, "reference_id": config.voice, "format": config.format,
                      "latency": "balanced"}
        if config.format == "pcm":
            body["sample_rate"] = config.sample_rate
        if config.speed is not None:
            body["prosody"] = {"speed": config.speed}
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/tts",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}",
                            "model": config.model},
                "json": body}

    async def synthesize(self, text, config, usage):
        usage.tokens["utf8_bytes"] = usage.tokens.get("utf8_bytes", 0.0) + len(
            text.encode("utf-8"))
        async for chunk in super().synthesize(text, config, usage):
            yield chunk
