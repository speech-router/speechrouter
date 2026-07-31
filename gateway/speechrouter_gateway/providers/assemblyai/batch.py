"""AssemblyAI batch STT (/v2 upload + transcript job)."""

import asyncio

import httpx

from ...config import Settings
from ...protocol import Transcript, Word
from ..base import ProviderStreamError, STTBatchProvider, STTConfig
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import CAPABILITIES, speaker_to_int

API_BASE = "https://api.assemblyai.com"
POLL_INTERVAL = 2.0
POLL_BUDGET_SECONDS = 1800.0


def build_job(audio_url: str, config: STTConfig) -> dict:
    # speech_model was deprecated live (2026-07-31): array form now required
    job: dict = {"audio_url": audio_url, "speech_models": [config.model]}
    if config.language:
        job["language_code"] = config.language
    else:
        job["language_detection"] = True
    if config.diarization:
        job["speaker_labels"] = True
    if config.keyterms:
        job["word_boost"] = list(config.keyterms)
    job.update(config.provider_params)
    return job


def parse_transcript(payload: dict, include_raw: bool = False) -> Transcript:
    words = [
        Word(
            w=w["text"],
            start=w["start"] / 1000.0,
            end=w["end"] / 1000.0,
            conf=w.get("confidence"),
            speaker=speaker_to_int(w.get("speaker")),
        )
        for w in payload.get("words") or []
        if w.get("start") is not None
    ]
    return Transcript(
        type="transcript",
        is_final=True,
        text=payload.get("text") or "",
        words=words or None,
        start=0.0,
        end=words[-1].end if words else None,
        lang=payload.get("language_code"),
        provider_raw=payload if include_raw else None,
    )


@register_stt_batch("assemblyai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "AssemblyAISTTBatch":
    if not settings.assemblyai_api_key:
        raise ProviderNotConfigured("assemblyai")
    return AssemblyAISTTBatch(settings.assemblyai_api_key)


class AssemblyAISTTBatch(STTBatchProvider):
    name = "assemblyai"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, api_base: str = API_BASE):
        self._api_base = api_base
        self._headers = {"Authorization": api_key}  # no Bearer

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        async with httpx.AsyncClient(base_url=self._api_base, headers=self._headers,
                                     timeout=120.0) as client:
            upload = await self._check(
                await client.post("/v2/upload", content=audio,
                                  headers={"Content-Type": "application/octet-stream"}),
                "upload",
            )
            job = await self._check(
                await client.post("/v2/transcript",
                                  json=build_job(str(upload["upload_url"]), config)),
                "create",
            )
            job_id = str(job["id"])
            deadline = asyncio.get_running_loop().time() + POLL_BUDGET_SECONDS
            while True:
                status = await self._check(
                    await client.get(f"/v2/transcript/{job_id}"), "poll"
                )
                state = status.get("status")
                if state == "completed":
                    return parse_transcript(status, config.include_raw)
                if state == "error":
                    raise ProviderStreamError(
                        f"assemblyai job failed: {status.get('error', '')}",
                        recoverable=False,
                        provider=self.name,
                    )
                if asyncio.get_running_loop().time() > deadline:
                    raise ProviderStreamError(
                        "assemblyai job polling timed out", recoverable=True,
                        provider=self.name, code="timeout",
                    )
                await asyncio.sleep(POLL_INTERVAL)

    async def _check(self, response: httpx.Response, stage: str) -> dict:
        if response.status_code != 200:
            raise ProviderStreamError(
                f"assemblyai {stage} {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500,
                provider=self.name,
                code=str(response.status_code),
            )
        return response.json()
