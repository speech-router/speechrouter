"""Inworld TTS: POST https://api.inworld.ai/tts/v1/voice:stream (docs/providers/tts/inworld.md).

- `Authorization: Basic <portal credential>` (used as-is).
- Body {text (<=4000), voiceId, modelId, audioConfig{audioEncoding,
  sampleRateHertz, speakingRate}, language?}.
- Response: NDJSON lines {"result":{"audioContent": b64, "usage":{...}}}; a
  stream can end with {"error":{...}} after HTTP 200. PCM = raw s16le.
- Billed per character (UTF-16 code units); usage.processedCharactersCount.
"""

import base64

import httpx

from ...config import Settings, tts_base_url
from ..base import ProviderStreamError, TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.inworld.ai"

CAPABILITIES = TTSCapabilities(
    default_voice="Ashley",
    formats=frozenset({"pcm", "mp3", "opus", "flac", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 22050, 24000, 44100, 48000}),
    format_rates={"mulaw": frozenset({8000}), "alaw": frozenset({8000})},
    max_input_chars=4000,
    speed=True,
)

_ENCODING = {"pcm": "PCM", "mp3": "MP3", "opus": "OGG_OPUS", "flac": "FLAC",
             "mulaw": "MULAW", "alaw": "ALAW"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("inworld", capabilities=CAPABILITIES)
def build(settings: Settings) -> "InworldTTS":
    if not settings.inworld_api_key:
        raise ProviderNotConfigured("inworld")
    return InworldTTS({"key": settings.inworld_api_key,
                       "base": tts_base_url(settings, "inworld", BASE)}, TRANSPORT)


class InworldTTS(HTTPStreamTTS, TTSProvider):
    name = "inworld"
    capabilities = CAPABILITIES
    response_mode = "ndjson"

    def build_request(self, text, config):
        audio: dict = {"audioEncoding": _ENCODING[config.format]}
        if config.format in {"pcm", "mulaw", "alaw"}:
            audio["sampleRateHertz"] = config.sample_rate
        if config.speed is not None:
            audio["speakingRate"] = config.speed
        body: dict = {"text": text, "voiceId": config.voice, "modelId": config.model,
                      "audioConfig": audio}
        if config.language:
            body["language"] = config.language
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/tts/v1/voice:stream",
                "headers": {"Authorization": f"Basic {self.credentials['key']}"},
                "json": body}

    def check_event(self, event):
        if "error" in event:
            raise ProviderStreamError(f"inworld stream error: {event['error']}",
                                      recoverable=False, provider=self.name,
                                      code="stream_error")

    def audio_from_event(self, event):
        data = (event.get("result") or {}).get("audioContent")
        return base64.b64decode(data) if data else None

    def on_event_usage(self, event, usage):
        count = ((event.get("result") or {}).get("usage") or {}).get(
            "processedCharactersCount")
        if isinstance(count, int) and count > 0:
            usage.characters = count
