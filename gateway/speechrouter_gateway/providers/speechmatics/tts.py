"""Speechmatics TTS (preview): POST https://preview.tts.speechmatics.com/generate/<voice>
(docs/providers/tts/speechmatics.md).

- `Authorization: Bearer`; body {"text"}; ?output_format=pcm_16000 (raw s16le
  16 kHz mono, the only pcm rate). English voices sarah, theo, megan, jack.
- Pricing page lists $0.011 / 1K chars; the docs still call the endpoint a
  free preview (UNVERIFIED which applies). No model id: slug speechmatics/preview.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://preview.tts.speechmatics.com"

CAPABILITIES = TTSCapabilities(
    default_voice="megan",
    formats=frozenset({"pcm"}),
    sample_rates=frozenset({16000}),
    max_input_chars=2000,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("speechmatics", capabilities=CAPABILITIES)
def build(settings: Settings) -> "SpeechmaticsTTS":
    if not settings.speechmatics_api_key:
        raise ProviderNotConfigured("speechmatics")
    return SpeechmaticsTTS({"key": settings.speechmatics_api_key,
                            "base": tts_base_url(settings, "speechmatics", BASE)}, TRANSPORT)


class SpeechmaticsTTS(HTTPStreamTTS, TTSProvider):
    name = "speechmatics"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        return {"url": f"{self.credentials['base']}/generate/{config.voice}",
                "params": {"output_format": "pcm_16000"},
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": {"text": text}}
