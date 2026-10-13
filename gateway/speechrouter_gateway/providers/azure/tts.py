"""Azure AI Speech TTS: POST {region}.tts.speech.microsoft.com/cognitiveservices/v1
(docs/providers/tts/azure.md).

- `Ocp-Apim-Subscription-Key` + region; SSML body; `X-Microsoft-OutputFormat`
  header picks the encoding; raw audio streams back.
- Slugs are voice tiers: azure/neural (`en-US-JennyNeural`) and
  azure/neural-hd (Dragon HD: `en-US-Ava:DragonHDLatestNeural`).
- Billed per character of TEXT (the gateway's SSML wrapper is not counted;
  whether Azure bills markup is UNVERIFIED). Prices from the official retail
  prices API (prices.azure.com, eastus), checked 2026-10-13.
"""

from xml.sax.saxutils import escape, quoteattr

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts

CAPABILITIES = TTSCapabilities(
    default_voice="en-US-JennyNeural",
    formats=frozenset({"pcm", "mp3", "opus", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 24000, 48000}),
    format_rates={"mulaw": frozenset({8000}), "alaw": frozenset({8000})},
    max_input_chars=5000,
    speed=True,
)

_PCM = {8000: "raw-8khz-16bit-mono-pcm", 16000: "raw-16khz-16bit-mono-pcm",
        24000: "raw-24khz-16bit-mono-pcm", 48000: "raw-48khz-16bit-mono-pcm"}
_OTHER = {"mp3": "audio-24khz-48kbitrate-mono-mp3", "opus": "ogg-24khz-16bit-mono-opus",
          "mulaw": "raw-8khz-8bit-mono-mulaw", "alaw": "raw-8khz-8bit-mono-alaw"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("azure", capabilities=CAPABILITIES)
def build(settings: Settings) -> "AzureTTS":
    if not (settings.azure_speech_key and settings.azure_speech_region):
        raise ProviderNotConfigured("azure")
    base = f"https://{settings.azure_speech_region}.tts.speech.microsoft.com"
    return AzureTTS({"key": settings.azure_speech_key,
                     "base": tts_base_url(settings, "azure", base)}, TRANSPORT)


def output_format(fmt: str, rate: int) -> str:
    return _PCM[rate] if fmt == "pcm" else _OTHER[fmt]


def build_ssml(text: str, voice: str, language: str | None, speed: float | None) -> str:
    lang = language or "-".join(voice.split("-")[:2]) or "en-US"
    body = escape(text)
    if speed is not None:
        body = f"<prosody rate={quoteattr(f'{speed:.2f}')}>{body}</prosody>"
    return (f"<speak version='1.0' xml:lang={quoteattr(lang)}>"
            f"<voice name={quoteattr(voice)}>{body}</voice></speak>")


class AzureTTS(HTTPStreamTTS, TTSProvider):
    name = "azure"
    capabilities = CAPABILITIES

    def describe_error(self, status, body, config):
        # Verified live: an unknown voice — e.g. Dragon HD in a region without
        # HD voices (westus lists none) — is a 400 with an EMPTY body.
        if status == 400 and not body.strip():
            return (f"voice '{config.voice}' is not available on this Azure Speech "
                    "resource's region (Dragon HD voices are region-limited)")
        return None

    def build_request(self, text, config):
        ssml = build_ssml(text, config.voice, config.language, config.speed)
        return {
            "url": f"{self.credentials['base']}/cognitiveservices/v1",
            "headers": {
                "Ocp-Apim-Subscription-Key": self.credentials["key"],
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": output_format(config.format, config.sample_rate),
                "User-Agent": "speechrouter-gateway",
            },
            "content": ssml.encode(),
        }
