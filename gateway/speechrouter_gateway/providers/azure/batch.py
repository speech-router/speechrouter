"""Azure fast transcription (synchronous REST) — the SDK-free batch path.

Facts (docs/providers/azure.md): POST {endpoint}/speechtotext/transcriptions:
transcribe?api-version=2025-10-15, multipart audio + definition JSON. This
API uses MILLISECOND units (offsetMilliseconds), unlike the SDK's 100-ns
ticks. <5h / <500MB. Diarization is mono-only, maxSpeakers 2-35.

Realtime Azure (Speech SDK bridge) is a separate adapter — the USP WebSocket
protocol is undocumented, so streaming requires azure-cognitiveservices-speech
(optional dependency), tracked as remaining work.
"""

import json

import httpx

from ...config import Settings
from ...protocol import Transcript, Word
from ..base import Capabilities, ProviderStreamError, STTBatchProvider, STTConfig
from ..openai_compat import filename_for
from ..registry import ProviderNotConfigured, register_stt_batch

API_VERSION = "2025-10-15"

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,
    diarization=True,
    keyterms=True,
    keyterms_max=500,
    languages=frozenset({"auto"}),
)


def build_definition(config: STTConfig) -> dict:
    definition: dict = {}
    if config.language:
        definition["locales"] = [config.language]
    if config.diarization:
        definition["diarization"] = {"enabled": True, "maxSpeakers": 10}
    if config.keyterms:
        definition["phraseList"] = {"phrases": list(config.keyterms), "biasingWeight": 1.0}
    definition.update(config.provider_params)
    return definition


def _speaker(value) -> int | None:
    return value if isinstance(value, int) else None


def parse_response(payload: dict) -> Transcript:
    phrases = payload.get("phrases", [])
    words: list[Word] = []
    for phrase in phrases:
        for w in phrase.get("words", []):
            offset_ms = w.get("offsetMilliseconds")
            if offset_ms is None:
                continue
            words.append(
                Word(
                    w=w.get("text", ""),
                    start=offset_ms / 1000.0,
                    end=(offset_ms + w.get("durationMilliseconds", 0)) / 1000.0,
                    speaker=_speaker(phrase.get("speaker")),
                )
            )
    combined = payload.get("combinedPhrases", [])
    text = " ".join(p.get("text", "") for p in combined).strip() or " ".join(
        p.get("text", "") for p in phrases
    ).strip()
    duration_ms = payload.get("durationMilliseconds")
    locales = {p.get("locale") for p in phrases if p.get("locale")}
    return Transcript(
        type="transcript",
        is_final=True,
        text=text,
        words=words or None,
        start=0.0,
        end=duration_ms / 1000.0 if duration_ms is not None else (
            words[-1].end if words else None
        ),
        lang=next(iter(locales)) if len(locales) == 1 else None,
    )


@register_stt_batch("azure", capabilities=CAPABILITIES)
def build(settings: Settings) -> "AzureFastTranscription":
    if not settings.azure_speech_key or not settings.azure_speech_region:
        raise ProviderNotConfigured("azure")
    return AzureFastTranscription(settings.azure_speech_key, settings.azure_speech_region)


class AzureFastTranscription(STTBatchProvider):
    name = "azure"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, region: str, endpoint: str | None = None):
        self._api_key = api_key
        self._endpoint = endpoint or f"https://{region}.api.cognitive.microsoft.com"

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        url = (
            f"{self._endpoint}/speechtotext/transcriptions:transcribe"
            f"?api-version={API_VERSION}"
        )
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    url,
                    headers={"Ocp-Apim-Subscription-Key": self._api_key},
                    files={
                        "audio": (filename_for(content_type), audio, content_type),
                        "definition": (None, json.dumps(build_definition(config)),
                                       "application/json"),
                    },
                )
        except httpx.HTTPError as exc:
            raise ProviderStreamError(
                f"azure batch request failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        if response.status_code != 200:
            raise ProviderStreamError(
                f"azure batch {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500 or response.status_code == 429,
                provider=self.name,
                code=str(response.status_code),
            )
        return parse_response(response.json())
