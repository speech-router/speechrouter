"""Mistral Voxtral TTS: POST /v1/audio/speech, stream=true (docs/providers/tts/mistral.md).

- Bearer auth; body {model, input, voice_id, response_format, stream}.
- SSE, verified live 2026-10-13: `event: speech.audio.delta` with data
  {type, audio_data: base64}; then `speech.audio.done` with data {type,
  usage{prompt_tokens, completion_tokens, total_tokens}} (Mistral prices TTS
  per character, so the token usage is informational).
- Mistral pcm is FLOAT32 little-endian: converted here to s16le so the rest
  of the gateway (wrappers, G.711, duration) sees ordinary pcm. 24 kHz
  verified live (round-trip transcription of the real sample).
- No documented default voice: callers pass a voice_id (preset or saved).
"""

import array
import base64
import sys

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.mistral.ai"

CAPABILITIES = TTSCapabilities(
    formats=frozenset({"pcm", "mp3", "flac", "opus"}),
    sample_rates=frozenset({24000}),
    max_input_chars=4096,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("mistral", capabilities=CAPABILITIES)
def build(settings: Settings) -> "MistralTTS":
    if not settings.mistral_api_key:
        raise ProviderNotConfigured("mistral")
    return MistralTTS({"key": settings.mistral_api_key,
                       "base": tts_base_url(settings, "mistral", BASE)}, TRANSPORT)


def float32_to_s16(data: bytes) -> bytes:
    floats = array.array("f")
    floats.frombytes(data)
    if sys.byteorder == "big":
        floats.byteswap()
    out = array.array("h", (max(-32768, min(32767, int(round(f * 32767)))) for f in floats))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


class MistralTTS(HTTPStreamTTS, TTSProvider):
    name = "mistral"
    capabilities = CAPABILITIES
    response_mode = "sse"

    def build_request(self, text, config):
        body: dict = {"model": config.model, "input": text, "voice_id": config.voice,
                      "response_format": config.format, "stream": True}
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/audio/speech",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": body}

    def audio_from_event(self, event, state):
        data = event.get("audio_data")
        return base64.b64decode(data) if isinstance(data, str) and data else None

    async def synthesize(self, text, config, usage):
        carry = b""
        async for chunk in super().synthesize(text, config, usage):
            if config.format != "pcm":
                yield chunk
                continue
            data = carry + chunk  # float32 samples may straddle chunks
            cut = len(data) - len(data) % 4
            carry = data[cut:]
            if cut:
                yield float32_to_s16(data[:cut])
