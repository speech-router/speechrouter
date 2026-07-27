"""Deepgram batch STT (POST /v1/listen, sync).

Docs facts: raw binary body + Content-Type audio/*; response is the ONLY
chance to get the transcript (Deepgram stores nothing); 2GB cap; 10-min
processing timeout -> 504.
"""

import json
import urllib.parse

import httpx

from ...config import Settings
from ...protocol import Transcript, Word
from ..base import ProviderStreamError, STTBatchProvider, STTConfig
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import CAPABILITIES

API_BASE = "https://api.deepgram.com/v1/listen"
TIMEOUT_SECONDS = 630.0  # provider processing timeout is 600s


def build_params(config: STTConfig) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [
        ("model", config.model),
        ("punctuate", "true"),
        ("smart_format", "true"),
    ]
    if config.language:
        params.append(("language", config.language))
    if config.diarization:
        params.append(("diarize", "true"))
    if config.keyterms:
        if config.model.startswith(("nova-3", "flux")):
            params.extend(("keyterm", t) for t in config.keyterms)
        else:
            params.extend(("keywords", f"{t}:2") for t in config.keyterms)
    for key, value in config.provider_params.items():
        params.append((key, str(value)))
    return params


def parse_response(payload: dict) -> Transcript:
    channels = payload.get("results", {}).get("channels", [])
    alt = (channels[0].get("alternatives") or [{}])[0] if channels else {}
    words = [
        Word(
            w=w.get("punctuated_word") or w.get("word", ""),
            start=float(w["start"]),
            end=float(w["end"]),
            conf=w.get("confidence"),
            speaker=w.get("speaker"),
            lang=w.get("language"),
        )
        for w in alt.get("words", [])
    ]
    duration = payload.get("metadata", {}).get("duration")
    detected = channels[0].get("detected_language") if channels else None
    return Transcript(
        type="transcript",
        is_final=True,
        text=alt.get("transcript", ""),
        words=words or None,
        start=0.0,
        end=float(duration) if duration is not None else (words[-1].end if words else None),
        lang=detected,
    )


@register_stt_batch("deepgram", capabilities=CAPABILITIES)
def build(settings: Settings) -> "DeepgramSTTBatch":
    if not settings.deepgram_api_key:
        raise ProviderNotConfigured("deepgram")
    return DeepgramSTTBatch(settings.deepgram_api_key)


class DeepgramSTTBatch(STTBatchProvider):
    name = "deepgram"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, api_base: str = API_BASE):
        self._api_key = api_key
        self._api_base = api_base

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        url = f"{self._api_base}?{urllib.parse.urlencode(build_params(config))}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    content=audio,
                    headers={
                        "Authorization": f"Token {self._api_key}",
                        "Content-Type": content_type if content_type.startswith("audio/")
                        else "application/octet-stream",
                    },
                )
        except httpx.TimeoutException as exc:
            raise ProviderStreamError(
                "deepgram batch timed out", recoverable=True, provider=self.name, code="timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderStreamError(
                f"deepgram batch request failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        if response.status_code != 200:
            raise ProviderStreamError(
                f"deepgram batch {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500,
                provider=self.name,
                code=str(response.status_code),
            )
        try:
            return parse_response(response.json())
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise ProviderStreamError(
                f"deepgram batch returned unparseable body: {exc}",
                recoverable=False,
                provider=self.name,
            ) from exc
