"""Azure fast transcription (synchronous REST) — the SDK-free batch path.

Facts (docs/providers/azure.md): POST {endpoint}/speechtotext/transcriptions:
transcribe?api-version=2025-10-15, multipart audio + definition JSON. This
API uses MILLISECOND units (offsetMilliseconds), unlike the SDK's 100-ns
ticks. <5h / <500MB. Diarization is mono-only, maxSpeakers 2-35.

MAI-Transcribe rides the same endpoint: an `enhancedMode` block naming the
model switches the request to Microsoft's in-house model (docs/providers/
azure.md § MAI-Transcribe). Word timings are opt-in there
(modelOptions.timestamps, default "none"), locales takes ONE bare language
code, and only MAI-Transcribe-2 diarizes.

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


# our model name -> enhancedMode.model, spelled as each doc revision's wire
# examples spell it (the 1.5 examples are lowercase, the 2 examples are not)
MAI_MODELS = {
    "mai-transcribe-2": "MAI-Transcribe-2",
    "mai-transcribe-1.5": "mai-transcribe-1.5",
}
_MAI_DIARIZE_MODELS = {"mai-transcribe-2"}


def _merge(base: dict, override: dict) -> dict:
    """provider_params win, but nested objects merge instead of replacing, so
    {"enhancedMode": {"modelOptions": {...}}} keeps the adapter's model."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _mai_definition(config: STTConfig) -> dict:
    enhanced: dict = {"enabled": True, "model": MAI_MODELS[config.model]}
    if config.model == "mai-transcribe-2":
        enhanced["modelOptions"] = {"timestamps": "word"}
    definition: dict = {"enhancedMode": enhanced}
    if config.language and config.language != "auto":
        # one bare code ("en"), not a locale; "yue"/"fil" are already bare
        definition["locales"] = [config.language.split("-")[0].lower()]
    # 1.5 has no diarization; the flag is ignored like other non-diarizing
    # batch models (models.json carries the per-model truth)
    if config.diarization and config.model in _MAI_DIARIZE_MODELS:
        definition["diarization"] = {"enabled": True}
    if config.keyterms:
        definition["phraseList"] = {"phrases": list(config.keyterms)}
    return definition


def build_definition(config: STTConfig) -> dict:
    if config.model in MAI_MODELS:
        definition = _merge(_mai_definition(config), config.provider_params)
        if not isinstance(definition["enhancedMode"], dict):
            definition["enhancedMode"] = {}
        # the adapter owns which model runs — it decides the vendor meter
        definition["enhancedMode"].update(enabled=True, model=MAI_MODELS[config.model])
        return definition
    definition: dict = {}
    if config.language:
        definition["locales"] = [config.language]
    if config.diarization:
        definition["diarization"] = {"enabled": True, "maxSpeakers": 10}
    if config.keyterms:
        definition["phraseList"] = {"phrases": list(config.keyterms), "biasingWeight": 1.0}
    definition = _merge(definition, config.provider_params)
    if isinstance(definition.get("enhancedMode"), dict):
        # LLM Speech shares fast transcription's SKU; a MAI model does not
        definition["enhancedMode"].pop("model", None)
    return definition


def _speaker(value) -> int | None:
    return value if isinstance(value, int) else None


def parse_response(payload: dict, include_raw: bool = False) -> Transcript:
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
        provider_raw=payload if include_raw else None,
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
        return parse_response(response.json(), config.include_raw)
