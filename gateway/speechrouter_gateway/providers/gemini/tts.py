"""Gemini TTS adapter: models/{m}:streamGenerateContent?alt=sse.

Protocol facts (docs/providers/gemini.md, "TTS"; ai.google.dev speech-generation):
- Same Gemini API key as Live; sent as the `x-goog-api-key` header, never
  `?key=`, so it stays out of URLs and access logs.
- Body: contents[{role:user, parts:[{text}]}], generationConfig
  {responseModalities:["AUDIO"], speechConfig:{voiceConfig:{prebuiltVoiceConfig
  {voiceName}}, languageCode?}}. Multi-speaker (`multiSpeakerVoiceConfig`)
  is reachable through provider_params.speechConfig.
- Each SSE chunk: candidates[0].content.parts[].inlineData{mimeType:
  "audio/L16;codec=pcm;rate=24000", data:<base64>} — raw s16le mono 24 kHz
  is the ONLY output; wav/mulaw/alaw are gateway wrappers.
- Style is steered in natural language ("Say cheerfully: ..."), so
  `instructions` becomes a prefix of the prompt. Those words are billed as
  input tokens by Google, which is why usage comes from usageMetadata.
- usageMetadata {promptTokenCount, candidatesTokenCount}: prompt = TEXT in,
  candidates = AUDIO out. Treated as cumulative — the last one wins.
- Audio is billed at 25 tokens per second of output (Google pricing page);
  used only as a fallback estimate when usageMetadata never arrives.
"""

import base64
import math
from collections.abc import AsyncIterator

import httpx

from ...config import Settings
from ..base import ProviderStreamError, TTSCapabilities, TTSConfig, TTSProvider, TTSUsage
from ..http_tts import make_client, sse_events, status_error, wrap_transport_error
from ..registry import ProviderNotConfigured, register_tts

AUDIO_TOKENS_PER_SECOND = 25
CHARS_PER_TEXT_TOKEN = 4  # rough English estimate, fallback only
NATIVE_RATE = 24000

VOICES = frozenset({
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe",
    "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib",
    "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima",
    "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
})

CAPABILITIES = TTSCapabilities(
    voices=VOICES,
    default_voice="Kore",
    formats=frozenset({"pcm"}),
    sample_rates=frozenset({NATIVE_RATE}),
    max_input_chars=4096,
    instructions=True,
    speed=False,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("gemini", capabilities=CAPABILITIES)
def build(settings: Settings) -> "GeminiTTS":
    if not settings.gemini_api_key:
        raise ProviderNotConfigured("gemini")
    return GeminiTTS(settings.gemini_api_key, settings.gemini_base_url, TRANSPORT)


def build_body(text: str, config: TTSConfig) -> dict:
    prompt = text
    if config.instructions:
        prompt = f"{config.instructions.strip().rstrip(':')}: {text}"
    speech: dict = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": config.voice}}}
    if config.language:
        speech["languageCode"] = config.language
    params = dict(config.provider_params)
    if isinstance(params.get("speechConfig"), dict):
        # multi-speaker replaces the single voice entirely
        speech = {**speech, **params.pop("speechConfig")}
        if "multiSpeakerVoiceConfig" in speech:
            speech.pop("voiceConfig", None)
    generation = {"responseModalities": ["AUDIO"], "speechConfig": speech}
    extra_generation = params.pop("generationConfig", None)
    if isinstance(extra_generation, dict):
        for key, value in extra_generation.items():
            generation.setdefault(key, value)
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation}
    for key, value in params.items():
        body.setdefault(key, value)
    return body


def audio_parts(payload: dict) -> list[bytes]:
    out = []
    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                out.append(base64.b64decode(inline["data"]))
    return out


def apply_usage(usage: TTSUsage, payload: dict) -> bool:
    meta = payload.get("usageMetadata")
    if not isinstance(meta, dict):
        return False
    if "promptTokenCount" in meta:
        usage.tokens["text_input_tokens"] = float(meta["promptTokenCount"])
    if "candidatesTokenCount" in meta:
        usage.tokens["audio_output_tokens"] = float(meta["candidatesTokenCount"])
    return True


def estimate_usage(usage: TTSUsage, prompt_chars: int, audio_bytes: int) -> None:
    seconds = audio_bytes / (2 * NATIVE_RATE)
    usage.tokens["text_input_tokens"] = float(math.ceil(prompt_chars / CHARS_PER_TEXT_TOKEN))
    usage.tokens["audio_output_tokens"] = float(math.ceil(seconds * AUDIO_TOKENS_PER_SECOND))
    usage.estimated = True


class GeminiTTS(TTSProvider):
    name = "gemini"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, base_url: str, transport=None):
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def synthesize(
        self, text: str, config: TTSConfig, usage: TTSUsage
    ) -> AsyncIterator[bytes]:
        usage.characters += len(text)
        body = build_body(text, config)
        prompt_chars = len(body["contents"][0]["parts"][0]["text"])
        url = f"{self._base}/v1beta/models/{config.model}:streamGenerateContent?alt=sse"
        self._client = self._client or make_client(self._transport)
        reported = False
        produced = 0
        try:
            async with self._client.stream(
                "POST", url, json=body, headers={"x-goog-api-key": self._api_key}
            ) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")
                    raise status_error(self.name, resp.status_code, detail)
                async for event in sse_events(resp):
                    if "error" in event:
                        raise ProviderStreamError(
                            f"gemini stream error: {event['error']}",
                            recoverable=False, provider=self.name, code="stream_error",
                        )
                    for chunk in audio_parts(event):
                        produced += len(chunk)
                        yield chunk
                    reported = apply_usage(usage, event) or reported
        except httpx.HTTPError as exc:
            raise wrap_transport_error(self.name, exc) from exc
        finally:
            # nothing generated -> nothing billed upstream -> nothing estimated
            if not reported and produced:
                estimate_usage(usage, prompt_chars, produced)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
