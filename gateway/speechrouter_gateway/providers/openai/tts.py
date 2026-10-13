"""OpenAI TTS adapter: POST /v1/audio/speech, streamed.

Protocol facts (docs/providers/openai.md, "TTS"):
- JSON body {model, input, voice, response_format, speed?, instructions?}.
- gpt-4o-mini-tts accepts `stream_format: "sse"`: the response becomes
  `speech.audio.delta {audio: <base64>}` events and a final
  `speech.audio.done {usage: {input_tokens, output_tokens}}`. That is the
  ONLY place token usage appears, so the adapter always asks for SSE on
  token-priced models even when the client wants raw bytes.
- tts-1 / tts-1-hd reject SSE; they stream raw audio bytes (chunked) and are
  priced per input character — the gateway counts those itself.
- `instructions` is gpt-4o-mini-tts only; `speed` (0.25-4.0) is ignored
  by gpt-4o-mini-tts per docs, honoured by tts-1*.
- pcm = raw s16le mono 24 kHz, no header.

Token split: input_tokens are TEXT tokens, output_tokens are AUDIO tokens
(the endpoint's only output modality).
"""

import base64
import math
from collections.abc import AsyncIterator

import httpx

from ...config import Settings
from ..base import ProviderStreamError, TTSCapabilities, TTSConfig, TTSProvider, TTSUsage
from ..http_tts import make_client, sse_events, status_error, wrap_transport_error
from ..registry import ProviderNotConfigured, register_tts

_SSE_MODELS = {"gpt-4o-mini-tts"}

# Fallback estimate only (stream cancelled before speech.audio.done).
# Measured live 2026-10-13 (scripts/tts_live_probe.py): 91 audio tokens for
# 3.40 s = 26.8 tokens/s. (OpenAI's ~$0.015/min marketing figure implies 20.8.)
AUDIO_TOKENS_PER_SECOND = 26.8
CHARS_PER_TEXT_TOKEN = 4

VOICES = frozenset({
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer",
    "verse", "marin", "cedar",
})

CAPABILITIES = TTSCapabilities(
    voices=VOICES,  # per-model truth in models.json
    default_voice="alloy",
    formats=frozenset({"mp3", "opus", "aac", "flac", "wav", "pcm"}),
    sample_rates=frozenset({24000}),
    max_input_chars=4096,
    instructions=True,
    speed=True,
)

# tests inject httpx.MockTransport here
TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("openai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "OpenAITTS":
    if not settings.openai_api_key:
        raise ProviderNotConfigured("openai")
    return OpenAITTS(settings.openai_api_key, settings.openai_base_url, TRANSPORT)


def build_body(text: str, config: TTSConfig) -> dict:
    body: dict = {
        "model": config.model,
        "input": text,
        "voice": config.voice,
        "response_format": config.format,
    }
    if config.speed is not None:
        body["speed"] = config.speed
    if config.instructions:
        body["instructions"] = config.instructions
    if config.model in _SSE_MODELS:
        body["stream_format"] = "sse"
    # provider_params never override the fields the gateway owns
    for key, value in config.provider_params.items():
        body.setdefault(key, value)
    return body


def apply_usage(usage: TTSUsage, payload: dict) -> None:
    raw = payload.get("usage") or {}
    if "input_tokens" in raw:
        usage.tokens["text_input_tokens"] = float(raw["input_tokens"])
    if "output_tokens" in raw:
        usage.tokens["audio_output_tokens"] = float(raw["output_tokens"])


class OpenAITTS(TTSProvider):
    name = "openai"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, base_url: str, transport=None):
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/audio/speech"
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def synthesize(
        self, text: str, config: TTSConfig, usage: TTSUsage
    ) -> AsyncIterator[bytes]:
        usage.characters += len(text)
        body = build_body(text, config)
        self._client = self._client or make_client(self._transport)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with self._client.stream("POST", self._url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")
                    raise status_error(self.name, resp.status_code, detail)
                if body.get("stream_format") == "sse":
                    async for event in sse_events(resp):
                        kind = event.get("type")
                        if kind == "speech.audio.delta" and event.get("audio"):
                            yield base64.b64decode(event["audio"])
                        elif kind == "speech.audio.done":
                            apply_usage(usage, event)
                        elif kind == "error":
                            raise ProviderStreamError(
                                f"openai stream error: {event.get('error')}",
                                recoverable=False, provider=self.name, code="stream_error",
                            )
                else:
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            raise wrap_transport_error(self.name, exc) from exc

    def estimate_usage(
        self, text: str, config: TTSConfig, audio_seconds: float, usage: TTSUsage
    ) -> None:
        if config.model not in _SSE_MODELS or usage.tokens:
            return
        prompt = len(text) + len(config.instructions or "")
        usage.tokens["text_input_tokens"] = float(math.ceil(prompt / CHARS_PER_TEXT_TOKEN))
        usage.tokens["audio_output_tokens"] = float(
            math.ceil(audio_seconds * AUDIO_TOKENS_PER_SECOND)
        )
        usage.estimated = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
