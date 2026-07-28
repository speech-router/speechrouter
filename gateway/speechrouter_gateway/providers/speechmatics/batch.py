"""Speechmatics batch STT (jobs API, json-v2 output — same results grammar
as realtime, so one parser serves both)."""

import asyncio
import json

import httpx

from ...config import Settings
from ...protocol import Transcript
from ..base import ProviderStreamError, STTBatchProvider, STTConfig
from ..registry import ProviderNotConfigured, register_stt_batch
from .adapter import CAPABILITIES, results_to_words

API_BASE = "https://eu1.asr.api.speechmatics.com"
POLL_INTERVAL = 3.0
POLL_BUDGET_SECONDS = 1800.0


def build_job_config(config: STTConfig) -> dict:
    transcription: dict = {"language": config.language or "en", "operating_point": config.model}
    if config.diarization:
        transcription["diarization"] = "speaker"
    if config.keyterms:
        transcription["additional_vocab"] = [{"content": t} for t in config.keyterms]
    transcription.update(config.provider_params)
    return {"type": "transcription", "transcription_config": transcription}


def parse_json_v2(payload: dict, include_raw: bool = False) -> Transcript:
    results = payload.get("results", [])
    words = results_to_words(results)
    text = " ".join(w.w for w in words)
    return Transcript(
        type="transcript",
        is_final=True,
        text=text,
        words=words or None,
        start=0.0,
        end=words[-1].end if words else None,
        provider_raw=payload if include_raw else None,
    )


@register_stt_batch("speechmatics", capabilities=CAPABILITIES)
def build(settings: Settings) -> "SpeechmaticsSTTBatch":
    if not settings.speechmatics_api_key:
        raise ProviderNotConfigured("speechmatics")
    return SpeechmaticsSTTBatch(settings.speechmatics_api_key)


class SpeechmaticsSTTBatch(STTBatchProvider):
    name = "speechmatics"
    capabilities = CAPABILITIES

    def __init__(self, api_key: str, api_base: str = API_BASE):
        self._api_base = api_base
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def transcribe(self, audio: bytes, content_type: str, config: STTConfig) -> Transcript:
        async with httpx.AsyncClient(base_url=self._api_base, headers=self._headers,
                                     timeout=120.0) as client:
            created = await self._check(
                await client.post(
                    "/v2/jobs",
                    files={"data_file": ("audio", audio, content_type)},
                    data={"config": json.dumps(build_job_config(config))},
                ),
                "create",
                expect={200, 201},
            )
            job_id = str(created["id"])
            deadline = asyncio.get_running_loop().time() + POLL_BUDGET_SECONDS
            while True:
                status = await self._check(await client.get(f"/v2/jobs/{job_id}"), "poll")
                state = status.get("job", {}).get("status") or status.get("status")
                if state == "done":
                    break
                if state == "rejected":
                    raise ProviderStreamError(
                        f"speechmatics job rejected: {json.dumps(status)[:300]}",
                        recoverable=False, provider=self.name,
                    )
                if asyncio.get_running_loop().time() > deadline:
                    raise ProviderStreamError(
                        "speechmatics job polling timed out", recoverable=True,
                        provider=self.name, code="timeout",
                    )
                await asyncio.sleep(POLL_INTERVAL)
            transcript = await self._check(
                await client.get(f"/v2/jobs/{job_id}/transcript", params={"format": "json-v2"}),
                "transcript",
            )
            return parse_json_v2(transcript, config.include_raw)

    async def _check(self, response: httpx.Response, stage: str,
                     expect: set[int] | frozenset[int] = frozenset({200})) -> dict:
        if response.status_code not in expect:
            raise ProviderStreamError(
                f"speechmatics {stage} {response.status_code}: {response.text[:300]}",
                recoverable=response.status_code >= 500,
                provider=self.name,
                code=str(response.status_code),
            )
        return response.json()
