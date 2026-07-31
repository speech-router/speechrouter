"""Shared machinery for OpenAI-shaped batch transcription APIs.

OpenAI, Groq, and Mistral all speak POST <base>/audio/transcriptions with
multipart file + model, returning {text} or a verbose body with words.
Subclasses supply base URL, auth, and per-provider form extras.
"""

import httpx

from ..protocol import Transcript, Word
from .base import ProviderStreamError, STTBatchProvider, STTConfig

_EXT_BY_TYPE = {
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/mp4": "mp4", "audio/m4a": "m4a", "audio/x-m4a": "m4a", "audio/flac": "flac",
    "audio/ogg": "ogg", "audio/webm": "webm",
}


def filename_for(content_type: str) -> str:
    return f"audio.{_EXT_BY_TYPE.get(content_type.split(';')[0].strip(), 'wav')}"


def parse_openai_response(payload: dict, include_raw: bool = False) -> Transcript:
    words = [
        Word(
            w=w.get("word") or w.get("text", ""),
            start=float(w["start"]),
            end=float(w["end"]),
            speaker=w.get("speaker") if isinstance(w.get("speaker"), int) else None,
        )
        for w in payload.get("words") or []
        if w.get("start") is not None
    ]
    duration = payload.get("duration")
    # diarized_json variants carry speakers on segments, not words: surface
    # each speaker turn as one segment-level Word (letters -> ints) so the
    # wire schema's words[].speaker carries diarization for these models too.
    segments = payload.get("segments") or []
    if not words:
        words = [
            Word(
                w=seg.get("text", "").strip(),
                start=float(seg["start"]),
                end=float(seg["end"]),
                speaker=(ord(sp.upper()) - ord("A"))
                if isinstance(sp := seg.get("speaker"), str)
                and len(sp) == 1 and sp.isalpha()
                else sp if isinstance(sp, int) else None,
            )
            for seg in segments
            if seg.get("start") is not None and seg.get("text", "").strip()
        ] or None
        words = words or []
    return Transcript(
        type="transcript",
        is_final=True,
        text=payload.get("text", ""),
        words=words or None,
        start=0.0,
        end=float(duration) if duration is not None else (
            words[-1].end if words else (segments[-1].get("end") if segments else None)
        ),
        lang=payload.get("language"),
        provider_raw=payload if include_raw else None,
    )


class OpenAICompatBatch(STTBatchProvider):
    """Subclass and set: name, capabilities, base_url; override _headers()
    and extra_form() as needed."""

    base_url: str
    verbose_supported: bool = True  # request word timestamps via verbose_json

    def __init__(self, api_key: str, base_url: str | None = None):
        self._api_key = api_key
        if base_url:
            self.base_url = base_url

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def wants_verbose(self, config: STTConfig) -> bool:
        return self.verbose_supported

    def extra_form(self, config: STTConfig) -> dict[str, str]:
        return {}

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        data: dict[str, str] = {"model": config.model}
        if config.language:
            data["language"] = config.language
        verbose = self.wants_verbose(config)
        if verbose:
            data["response_format"] = "verbose_json"
            data["timestamp_granularities[]"] = "word"
        else:
            data["response_format"] = "json"
        data.update(self.extra_form(config))
        data.update({k: str(v) for k, v in config.provider_params.items()})
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=self._headers(),
                    data=data,
                    files={"file": (filename_for(content_type), audio, content_type)},
                )
        except httpx.TimeoutException as exc:
            raise ProviderStreamError(
                f"{self.name} batch timed out", recoverable=True, provider=self.name,
                code="timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderStreamError(
                f"{self.name} batch request failed: {exc}", recoverable=True,
                provider=self.name,
            ) from exc
        if response.status_code != 200:
            raise ProviderStreamError(
                f"{self.name} batch {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500 or response.status_code == 429,
                provider=self.name,
                code=str(response.status_code),
            )
        return parse_openai_response(response.json(), config.include_raw)
