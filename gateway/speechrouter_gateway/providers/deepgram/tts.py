"""Deepgram Aura TTS: POST /v1/speak (docs/providers/tts/deepgram.md).

- `Authorization: Token`; body {"text"} (max 2000 chars); everything else is
  query: model (= the VOICE, e.g. aura-2-thalia-en), encoding, container,
  sample_rate. Chunked raw audio back; `dg-char-count` reports billed chars.
- Catalog slugs are the families (deepgram/aura-2, deepgram/aura-1); the
  request's `voice` is the full Deepgram model id. Billed per character.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.deepgram.com"

CAPABILITIES = TTSCapabilities(
    default_voice="aura-2-thalia-en",
    formats=frozenset({"pcm", "mp3", "opus", "flac", "aac", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 24000, 32000, 48000}),
    format_rates={"mulaw": frozenset({8000, 16000}), "alaw": frozenset({8000, 16000})},
    max_input_chars=2000,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("deepgram", capabilities=CAPABILITIES)
def build(settings: Settings) -> "DeepgramTTS":
    if not settings.deepgram_api_key:
        raise ProviderNotConfigured("deepgram")
    return DeepgramTTS({"key": settings.deepgram_api_key,
                        "base": tts_base_url(settings, "deepgram", BASE)}, TRANSPORT)


def query(fmt: str, rate: int, voice: str) -> dict:
    params: dict = {"model": voice}
    if fmt in {"pcm", "mulaw", "alaw"}:
        params.update(encoding="linear16" if fmt == "pcm" else fmt, container="none",
                      sample_rate=rate)
    elif fmt == "opus":
        params.update(encoding="opus", container="ogg")
    else:  # mp3 / flac / aac: fixed rates server-side
        params["encoding"] = fmt
    return params


class DeepgramTTS(HTTPStreamTTS, TTSProvider):
    name = "deepgram"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        return {
            "url": f"{self.credentials['base']}/v1/speak",
            "params": {**query(config.format, config.sample_rate, config.voice),
                       **config.provider_params},
            "headers": {"Authorization": f"Token {self.credentials['key']}"},
            "json": {"text": text},
        }

    def on_headers(self, headers, usage):
        count = headers.get("dg-char-count")
        if count and count.isdigit():
            usage.characters = int(count)  # Deepgram's own billed count wins
