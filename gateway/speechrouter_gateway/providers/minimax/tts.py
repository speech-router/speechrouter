"""MiniMax T2A v2: POST https://api.minimax.io/v1/t2a_v2, stream=true
(docs/providers/tts/minimax.md).

- `Authorization: Bearer`; body {model, text, stream:true, voice_setting
  {voice_id, speed}, audio_setting{format, sample_rate, channel}, language_boost?}.
- SSE: data.audio is HEX audio; data.status 1 while generating, 2 on the final
  event, which carries extra_info (usage_characters = billed characters) and
  MAY repeat the whole audio — skipped once audio has streamed.
- Errors can arrive in-band: base_resp.status_code != 0 (1004 auth, 1008
  balance, 1002 rate limit). Billed per character.
"""

import httpx

from ...config import Settings, tts_base_url
from ..base import ProviderStreamError, TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

BASE = "https://api.minimax.io"

CAPABILITIES = TTSCapabilities(
    default_voice="English_expressive_narrator",
    formats=frozenset({"pcm", "mp3", "flac", "opus", "mulaw"}),
    sample_rates=frozenset({8000, 16000, 22050, 24000, 32000, 44100}),
    format_rates={"mulaw": frozenset({8000})},
    max_input_chars=4096,
    speed=True,
)

_FORMAT = {"pcm": "pcm", "mp3": "mp3", "flac": "flac", "opus": "opus", "mulaw": "pcmu_raw"}
_AUTH_CODES = {1004, 2049}
_RETRY_CODES = {1000, 1001, 1002, 1024, 1033}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("minimax", capabilities=CAPABILITIES)
def build(settings: Settings) -> "MiniMaxTTS":
    if not settings.minimax_api_key:
        raise ProviderNotConfigured("minimax")
    return MiniMaxTTS({"key": settings.minimax_api_key,
                       "base": tts_base_url(settings, "minimax", BASE)}, TRANSPORT)


class MiniMaxTTS(HTTPStreamTTS, TTSProvider):
    name = "minimax"
    capabilities = CAPABILITIES
    response_mode = "sse"

    def __init__(self, credentials, transport=None):
        super().__init__(credentials, transport)
        self._streamed = False

    def build_request(self, text, config):
        self._streamed = False
        voice: dict = {"voice_id": config.voice}
        if config.speed is not None:
            voice["speed"] = config.speed
        audio: dict = {"format": _FORMAT[config.format], "channel": 1}
        if config.format in {"pcm", "mulaw", "flac"}:
            audio["sample_rate"] = config.sample_rate
        body: dict = {"model": config.model, "text": text, "stream": True,
                      "voice_setting": voice, "audio_setting": audio}
        if config.language:
            body["language_boost"] = config.language
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/t2a_v2",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": body}

    def check_event(self, event):
        base = event.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code:
            raise ProviderStreamError(
                f"minimax error {code}: {base.get('status_msg', '')}",
                recoverable=code in _RETRY_CODES, provider=self.name,
                code="auth" if code in _AUTH_CODES else f"minimax_{code}")

    def audio_from_event(self, event):
        data = event.get("data") or {}
        audio = data.get("audio")
        if not audio:
            return None
        if data.get("status") == 2 and self._streamed:
            return None  # final summary event repeats the whole clip
        self._streamed = True
        return bytes.fromhex(audio)

    def on_event_usage(self, event, usage):
        count = (event.get("extra_info") or {}).get("usage_characters")
        if isinstance(count, int) and count > 0:
            usage.characters = count
