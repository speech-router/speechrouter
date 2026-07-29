from __future__ import annotations

import json
from typing import Any, BinaryIO
from urllib.parse import urlencode

import httpx

from .errors import SpeechRouterError
from .stream import ListenStream

DEFAULT_BASE = "https://api.speechrouter.ai"


class SpeechRouter:
    """One API for every speech model — https://speechrouter.ai

        sr = SpeechRouter(api_key="sk_sr_...")
        async with sr.listen(model="deepgram/nova-3") as stream:
            ...
        result = await sr.transcribe(model="deepgram/nova-3", file=open("a.wav", "rb"))
    """

    def __init__(self, *, api_key: str, base_url: str = DEFAULT_BASE, timeout: float = 630.0):
        if not api_key:
            raise SpeechRouterError("api_key is required", code="auth_failed")
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._ws_base = self._base.replace("http", "ws", 1)
        self._timeout = timeout

    def listen(
        self,
        *,
        model: str,
        fallbacks: list[str] | None = None,
        encoding: str = "linear16",
        sample_rate: int = 16000,
        channels: int = 1,
        language: str | None = None,
        interim_results: bool = True,
        diarization: bool = False,
        keyterms: list[str] | None = None,
        include_raw: bool = False,
        provider_params: dict[str, Any] | None = None,
        connect_timeout: float = 10.0,
        keepalive: float | None = 8.0,
    ) -> ListenStream:
        """Open a live transcription session (async context manager)."""
        query: dict[str, str] = {
            "model": model,
            "encoding": encoding,
            "sample_rate": str(sample_rate),
            "channels": str(channels),
        }
        if fallbacks:
            query["fallbacks"] = ",".join(fallbacks)
        if language:
            query["language"] = language
        if not interim_results:
            query["interim_results"] = "false"
        if diarization:
            query["diarization"] = "true"
        if keyterms:
            query["keyterms"] = ",".join(keyterms)
        if include_raw:
            query["include_raw"] = "true"
        if provider_params:
            query["provider_params"] = json.dumps(provider_params)
        url = f"{self._ws_base}/v1/listen?{urlencode(query)}"
        return ListenStream(
            url, api_key=self._api_key, connect_timeout=connect_timeout, keepalive=keepalive
        )

    async def transcribe(
        self,
        *,
        model: str,
        file: bytes | BinaryIO | None = None,
        url: str | None = None,
        filename: str = "audio",
        response_format: str = "json",
        language: str | None = None,
        diarization: bool = False,
        keyterms: list[str] | None = None,
        include_raw: bool = False,
        provider_params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | str:
        """Transcribe a complete file (or a URL the gateway fetches).

        Returns a dict for json/verbose_json, a string for srt/vtt/text.
        """
        data: dict[str, str] = {"model": model, "response_format": response_format}
        if language:
            data["language"] = language
        if diarization:
            data["diarization"] = "true"
        if keyterms:
            data["keyterms"] = ",".join(keyterms)
        if include_raw:
            data["include_raw"] = "true"
        if provider_params:
            data["provider_params"] = json.dumps(provider_params)

        files = None
        if url is not None:
            data["url"] = url
        elif file is not None:
            files = {"file": (filename, file)}
        else:
            raise SpeechRouterError("transcribe needs a file or a url", code="invalid_request")

        response = await self._request(
            "POST", "/v1/audio/transcriptions", data=data, files=files
        )
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    async def create_token(self, ttl_seconds: int = 60) -> dict[str, Any]:
        """Mint a short-lived token for client-side use (browsers, mobile).

        Call from your backend with the real key; hand the returned token to
        the client, which uses it as its api_key. TTL limits connecting, not
        session length. Returns {"token", "expires_at", "ttl_seconds"}.
        """
        response = await self._request("POST", "/v1/tokens", json={"ttl_seconds": ttl_seconds})
        return response.json()

    async def list_models(self) -> list[dict[str, Any]]:
        """The live model catalog — slugs, capabilities, pricing."""
        response = await self._request("GET", "/v1/models")
        return response.json().get("data", [])

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.request(
                    method,
                    f"{self._base}{path}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    **kwargs,
                )
        except httpx.HTTPError as e:
            raise SpeechRouterError(f"network request failed: {e}", code="connection_failed") from e
        if response.is_success:
            return response
        code, message = "internal_error", f"HTTP {response.status_code}"
        recoverable = response.status_code >= 500 or response.status_code == 429
        try:
            error = response.json().get("error", {})
            code = error.get("code", code)
            message = error.get("message", message)
            if isinstance(error.get("recoverable"), bool):
                recoverable = error["recoverable"]
        except Exception:  # noqa: BLE001, S110 - non-JSON error body keeps the status line
            pass
        raise SpeechRouterError(
            message, code=code, status=response.status_code, recoverable=recoverable
        )
