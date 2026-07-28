"""ElevenLabs Scribe batch STT (POST /v1/speech-to-text)."""

import httpx

from ...config import Settings
from ...protocol import Transcript, Word
from ..base import Capabilities, ProviderStreamError, STTBatchProvider, STTConfig
from ..openai_compat import filename_for
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import speaker_to_int

API_URL = "https://api.elevenlabs.io/v1/speech-to-text"

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,
    diarization=True,
    keyterms=True,
    keyterms_max=1000,
    languages=frozenset({"auto"}),
)


def parse_response(payload: dict, include_raw: bool = False) -> Transcript:
    words = [
        Word(
            w=w["text"],
            start=float(w["start"]),
            end=float(w["end"]),
            speaker=speaker_to_int(w.get("speaker_id")),
        )
        for w in payload.get("words") or []
        if w.get("type") == "word" and w.get("start") is not None
    ]
    return Transcript(
        type="transcript",
        is_final=True,
        text=payload.get("text", ""),
        words=words or None,
        start=0.0,
        end=words[-1].end if words else None,
        lang=payload.get("language_code"),
        provider_raw=payload if include_raw else None,
    )


@register_stt_batch("elevenlabs", capabilities=CAPABILITIES)
def build(settings: Settings) -> "ElevenLabsSTTBatch":
    if not settings.elevenlabs_api_key:
        raise ProviderNotConfigured("elevenlabs")
    return ElevenLabsSTTBatch(settings.elevenlabs_api_key)


class ElevenLabsSTTBatch(STTBatchProvider):
    name = "elevenlabs"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, api_url: str = API_URL):
        self._api_key = api_key
        self._api_url = api_url

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        data: dict[str, str] = {
            "model_id": config.model,
            "timestamps_granularity": "word",
        }
        if config.language:
            data["language_code"] = config.language
        if config.diarization:
            data["diarize"] = "true"
        if config.keyterms:
            data["keyterms"] = ",".join(config.keyterms)
        data.update({k: str(v) for k, v in config.provider_params.items()})
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    self._api_url,
                    headers={"xi-api-key": self._api_key},
                    data=data,
                    files={"file": (filename_for(content_type), audio, content_type)},
                )
        except httpx.HTTPError as exc:
            raise ProviderStreamError(
                f"elevenlabs batch request failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        if response.status_code != 200:
            raise ProviderStreamError(
                f"elevenlabs batch {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500 or response.status_code == 429,
                provider=self.name,
                code=str(response.status_code),
            )
        return parse_response(response.json(), config.include_raw)
