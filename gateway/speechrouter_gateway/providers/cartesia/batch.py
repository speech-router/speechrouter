"""Cartesia batch STT (POST /stt, ink-whisper only — ink-2 has no batch)."""

import httpx

from ...config import Settings
from ...protocol import Transcript, Word
from ..base import Capabilities, ProviderStreamError, STTBatchProvider, STTConfig
from ..openai_compat import filename_for
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import CARTESIA_VERSION

API_URL = "https://api.cartesia.ai/stt"

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,
    languages=frozenset({"auto"}),
)


def parse_response(payload: dict, include_raw: bool = False) -> Transcript:
    words = [
        Word(w=w["word"], start=float(w["start"]), end=float(w["end"]))
        for w in payload.get("words") or []
        if w.get("start") is not None
    ]
    duration = payload.get("duration")
    return Transcript(
        type="transcript",
        is_final=True,
        text=payload.get("text", ""),
        words=words or None,
        start=0.0,
        end=float(duration) if duration is not None else (words[-1].end if words else None),
        lang=payload.get("language"),
        provider_raw=payload if include_raw else None,
    )


@register_stt_batch("cartesia", capabilities=CAPABILITIES)
def build(settings: Settings) -> "CartesiaSTTBatch":
    if not settings.cartesia_api_key:
        raise ProviderNotConfigured("cartesia")
    return CartesiaSTTBatch(settings.cartesia_api_key)


class CartesiaSTTBatch(STTBatchProvider):
    name = "cartesia"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, api_url: str = API_URL):
        self._api_key = api_key
        self._api_url = api_url

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        data: dict[str, str] = {
            "model": config.model,
            "timestamp_granularities[]": "word",
        }
        if config.language:
            data["language"] = config.language
        data.update({k: str(v) for k, v in config.provider_params.items()})
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    self._api_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Cartesia-Version": CARTESIA_VERSION,
                    },
                    data=data,
                    files={"file": (filename_for(content_type), audio, content_type)},
                )
        except httpx.HTTPError as exc:
            raise ProviderStreamError(
                f"cartesia batch request failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        if response.status_code != 200:
            raise ProviderStreamError(
                f"cartesia batch {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500,
                provider=self.name,
                code=str(response.status_code),
            )
        return parse_response(response.json(), config.include_raw)
