"""xAI Grok Voice Transcribe batch (POST /v1/stt).

Facts (docs/providers/xai.md): NOT OpenAI-compatible — /v1/audio/
transcriptions is a 404. Multipart with option fields BEFORE `file` ("fields
sent after `file` may be ignored"); httpx writes `data` fields before
`files`, which is the order needed. Containers are auto-detected; raw audio
needs `audio_format` + `sample_rate` (provider_params). Word timestamps
(seconds) always come back; `language` in the response is the detected one.

`format=true` (inverse text normalization) requires `language`, so the
adapter sends it whenever a language is given — streaming turns ITN on from
`language` alone, and both modes should read the same.
"""

import httpx

from ...config import Settings
from ...protocol import Transcript
from ..base import Capabilities, ProviderStreamError, STTBatchProvider, STTConfig
from ..openai_compat import filename_for
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import LANGUAGES, api_language, parse_words, vendor_model

API_URL = "https://api.x.ai/v1/stt"

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,
    diarization=True,
    keyterms=True,
    keyterms_max=100,
    languages=frozenset({"auto", *LANGUAGES}),
)


def _field(value) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def build_form(config: STTConfig) -> dict[str, str | list[str]]:
    form: dict[str, str | list[str]] = {"model": vendor_model(config.model)}
    language = api_language(config.language)
    if language:
        form["language"] = language
        form["format"] = "true"
    if config.diarization:
        form["diarize"] = "true"
    if config.keyterms:
        form["keyterm"] = list(config.keyterms)
    for key, value in config.provider_params.items():
        if key in {"model", "file", "url"}:
            continue  # the slug picks the model (and the price); audio is ours
        form[key] = (
            [_field(v) for v in value] if isinstance(value, (list, tuple)) else _field(value)
        )
    return form


def parse_response(payload: dict, include_raw: bool = False) -> Transcript:
    words = parse_words(payload.get("words"))
    if not words and payload.get("channels"):
        # multichannel=true: per-channel words, merged here in time order
        words = sorted(
            (w for ch in payload["channels"] for w in parse_words(ch.get("words"))),
            key=lambda w: w.start,
        )
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


@register_stt_batch("xai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "XAIBatch":
    if not settings.xai_api_key:
        raise ProviderNotConfigured("xai")
    return XAIBatch(settings.xai_api_key)


class XAIBatch(STTBatchProvider):
    name = "xai"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, url: str = API_URL):
        self._api_key = api_key
        self._url = url

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data=build_form(config),
                    files={"file": (filename_for(content_type), audio, content_type)},
                )
        except httpx.TimeoutException as exc:
            raise ProviderStreamError(
                "xai batch timed out", recoverable=True, provider=self.name, code="timeout"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderStreamError(
                f"xai batch request failed: {exc}", recoverable=True, provider=self.name
            ) from exc
        if response.status_code != 200:
            raise ProviderStreamError(
                f"xai batch {response.status_code}: {response.text[:300]}",
                # 429 = back off and retry, 5xx = backend unavailable; a bad key
                # is 400 live and 401 per the docs — neither is retryable
                recoverable=response.status_code >= 500 or response.status_code == 429,
                provider=self.name,
                code=str(response.status_code),
            )
        return parse_response(response.json(), config.include_raw)
