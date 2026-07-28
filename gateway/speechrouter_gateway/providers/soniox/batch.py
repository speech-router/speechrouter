"""Soniox async batch STT (files + transcriptions job API).

Docs facts (docs/providers/soniox.md): upload -> create transcription ->
poll -> fetch transcript. Files and transcriptions are NEVER auto-deleted
(10GB/1000-file quota), so cleanup runs in finally even on failure. Async
tokens carry no is_final and text is the full concatenated transcript.
"""

import asyncio

import httpx

from ...config import Settings
from ...logging import logger
from ...protocol import Transcript
from ..base import ProviderStreamError, STTBatchProvider, STTConfig
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import CAPABILITIES as STREAM_CAPABILITIES
from .adapter import _tokens_to_words

API_BASE = "https://api.soniox.com"
POLL_INTERVAL = 1.0
POLL_BUDGET_SECONDS = 900.0

CAPABILITIES = STREAM_CAPABILITIES  # same feature surface for async


def build_job(file_id: str, config: STTConfig) -> dict:
    job: dict = {"model": config.model, "file_id": file_id}
    if config.language:
        job["language_hints"] = [config.language]
        job["language_hints_strict"] = True
    if config.diarization:
        job["enable_speaker_diarization"] = True
    if config.keyterms:
        job["context"] = {"terms": list(config.keyterms)}
    job.update(config.provider_params)
    return job


def parse_transcript(payload: dict, include_raw: bool = False) -> Transcript:
    tokens = [t for t in payload.get("tokens", []) if t.get("text", "").strip() not in
              {"<end>", "<fin>"}]
    words = _tokens_to_words(tokens)
    timed = [t for t in tokens if t.get("start_ms") is not None]
    end = round(max(t["end_ms"] for t in timed) / 1000.0, 3) if timed else None
    return Transcript(
        type="transcript",
        is_final=True,
        text=payload.get("text", ""),
        words=words or None,
        start=0.0,
        end=end,
        provider_raw=payload if include_raw else None,
    )


@register_stt_batch("soniox", capabilities=CAPABILITIES)
def build(settings: Settings) -> "SonioxSTTBatch":
    if not settings.soniox_api_key:
        raise ProviderNotConfigured("soniox")
    return SonioxSTTBatch(settings.soniox_api_key)


class SonioxSTTBatch(STTBatchProvider):
    name = "soniox"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, api_base: str = API_BASE):
        self._api_base = api_base
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        async with httpx.AsyncClient(base_url=self._api_base, headers=self._headers,
                                     timeout=60.0) as client:
            file_id: str | None = None
            job_id: str | None = None
            try:
                upload = await self._check(
                    await client.post(
                        "/v1/files", files={"file": ("audio", audio, content_type)}
                    ),
                    "upload",
                )
                file_id = str(upload["id"])
                job = await self._check(
                    await client.post("/v1/transcriptions", json=build_job(file_id, config)),
                    "create",
                )
                job_id = str(job["id"])
                await self._poll(client, job_id)
                transcript = await self._check(
                    await client.get(f"/v1/transcriptions/{job_id}/transcript"), "transcript"
                )
                return parse_transcript(transcript, config.include_raw)
            finally:
                # Soniox never auto-deletes; leaked artifacts hit hard quotas.
                for method, path in (
                    ("DELETE", f"/v1/transcriptions/{job_id}" if job_id else None),
                    ("DELETE", f"/v1/files/{file_id}" if file_id else None),
                ):
                    if path:
                        try:
                            await client.request(method, path)
                        except httpx.HTTPError:
                            logger.warning("soniox cleanup failed", extra={"path": path})

    async def _poll(self, client: httpx.AsyncClient, job_id: str) -> None:
        deadline = asyncio.get_running_loop().time() + POLL_BUDGET_SECONDS
        while True:
            status = await self._check(
                await client.get(f"/v1/transcriptions/{job_id}"), "poll"
            )
            state = status.get("status")
            if state == "completed":
                return
            if state == "error":
                raise ProviderStreamError(
                    f"soniox job failed: {status.get('error_message', '')}",
                    recoverable=False,
                    provider=self.name,
                    code=status.get("error_type", ""),
                )
            if asyncio.get_running_loop().time() > deadline:
                raise ProviderStreamError(
                    "soniox job polling timed out", recoverable=True, provider=self.name,
                    code="timeout",
                )
            await asyncio.sleep(POLL_INTERVAL)

    async def _check(self, response: httpx.Response, stage: str) -> dict:
        if response.status_code not in (200, 201):
            raise ProviderStreamError(
                f"soniox {stage} {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500,
                provider=self.name,
                code=str(response.status_code),
            )
        return response.json()
