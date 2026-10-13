"""Shared plumbing for HTTP-streaming TTS adapters (OpenAI, Gemini).

- One pooled httpx client per adapter instance; `transport` is injectable so
  tests run against httpx.MockTransport without a socket.
- SSE parsing: both vendors stream `data: {json}` lines.
- Error mapping: vendor status -> ProviderStreamError.code. 400s describe the
  caller's input (never our account state), so their message is safe to show;
  everything else is reported upstream and replaced by a customer-facing line.
"""

import json
import re
from collections.abc import AsyncIterator

import httpx

from .base import ProviderStreamError

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0  # gap between chunks, not total duration


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        transport=transport,
    )


# 4xx bodies that describe OUR provider account, not the caller's input.
# They must not be shown to customers as "invalid_request" (verified live:
# Groq returns 400 "requires terms acceptance ... org admin").
_ACCOUNT_HINTS = re.compile(
    r"terms acceptance|accept the terms|org admin|quota|billing|insufficient (funds|credit|"
    r"balance)|credit balance|subscription|payment required|api key|unauthori[sz]ed",
    re.IGNORECASE,
)


def status_error(provider: str, status: int, body: str) -> ProviderStreamError:
    if status in (400, 402, 403) and _ACCOUNT_HINTS.search(body):
        return ProviderStreamError(f"{provider} HTTP {status} (account): {body[:300]}",
                                   recoverable=False, provider=provider, code="account")
    code = {
        400: "invalid_request",
        401: "auth",
        403: "auth",
        404: "model_not_found",
        429: "rate_limited",
    }.get(status, "upstream_5xx" if status >= 500 else f"http_{status}")
    return ProviderStreamError(
        f"{provider} HTTP {status}: {body[:300]}",
        recoverable=status >= 500 or status == 429,
        provider=provider,
        code=code,
    )


async def sse_events(response: httpx.Response) -> AsyncIterator[dict]:
    """Yield each `data:` JSON payload. Multi-line data fields are joined."""
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
            continue
        if line == "" and buffer:
            raw = "\n".join(buffer)
            buffer = []
            if raw == "[DONE]":
                return
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload
    if buffer:
        try:
            payload = json.loads("\n".join(buffer))
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            yield payload


def wrap_transport_error(provider: str, exc: httpx.HTTPError) -> ProviderStreamError:
    code = "timeout" if isinstance(exc, httpx.TimeoutException) else "connect_failed"
    return ProviderStreamError(
        f"{provider}: {type(exc).__name__}: {exc}", recoverable=True, provider=provider, code=code
    )


# ------------------------------------------------------------------ base class
#
# Most TTS vendors are "POST text, audio comes back": they differ only in the
# request shape and in how audio rides the response. Subclasses declare both;
# synthesize() owns the streaming loop, error mapping and character counting.


class HTTPStreamTTS:
    """Mixin-style base for HTTP TTS adapters. Subclasses set:

    name, capabilities (TTSCapabilities), key_field (Settings attribute),
    response_mode:
      "bytes"      raw audio body, streamed (chunked transfer)
      "sse"        `data: {json}` events -> audio_from_event()
      "json"       one JSON document -> audio_from_event() (non-streaming APIs)
      "ndjson"     newline-delimited JSON objects -> audio_from_event()
    and implement build_request(text, config) -> dict(method, url, headers,
    json|content|data, params).
    """

    name: str = ""
    response_mode: str = "bytes"
    count_characters: bool = True  # usage.characters += len(text)

    def __init__(self, credentials: dict, transport: httpx.AsyncBaseTransport | None = None):
        self.credentials = credentials
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    # -- subclass hooks -----------------------------------------------------

    def build_request(self, text: str, config) -> dict:  # noqa: ANN001
        raise NotImplementedError

    def audio_from_event(self, event: dict, state: dict) -> bytes | None:
        """Audio carried by one SSE/JSON/NDJSON event (None if none). `state`
        is per synthesize() call: /v1/speak runs calls concurrently on one
        adapter, so per-stream bookkeeping must never live on self."""
        return None

    def check_event(self, event: dict) -> None:
        """Raise ProviderStreamError for in-band errors (HTTP 200 bodies)."""

    def on_headers(self, headers: httpx.Headers, usage) -> None:  # noqa: ANN001
        """Read usage reported in response headers."""

    def on_event_usage(self, event: dict, usage) -> None:  # noqa: ANN001
        """Read usage reported in an event."""

    def describe_error(self, status: int, body: str, config) -> str | None:  # noqa: ANN001
        """Replace an unhelpful vendor error body (e.g. Azure's empty 400)."""
        return None

    def strip_header(self, chunk: bytes, first: bool) -> bytes:
        """e.g. drop a WAV header when raw pcm was asked for."""
        return chunk

    # -- engine ---------------------------------------------------------------

    async def synthesize(self, text: str, config, usage) -> AsyncIterator[bytes]:  # noqa: ANN001
        if self.count_characters:
            usage.characters += len(text)
        spec = self.build_request(text, config)
        method = spec.pop("method", "POST")
        url = spec.pop("url")
        self._client = self._client or make_client(self._transport)
        first = True
        try:
            async with self._client.stream(method, url, **spec) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode(errors="replace")
                    detail = self.describe_error(resp.status_code, detail, config) or detail
                    raise status_error(self.name, resp.status_code, detail)
                self.on_headers(resp.headers, usage)
                if self.response_mode == "bytes":
                    async for chunk in resp.aiter_bytes():
                        chunk = self.strip_header(chunk, first)
                        first = False
                        if chunk:
                            yield chunk
                    return
                events = self._events(resp)
                state: dict = {}
                async for event in events:
                    self.check_event(event)
                    audio = self.audio_from_event(event, state)
                    if audio:
                        audio = self.strip_header(audio, first)
                        first = False
                        if audio:
                            yield audio
                    self.on_event_usage(event, usage)
        except httpx.HTTPError as exc:
            raise wrap_transport_error(self.name, exc) from exc

    async def _events(self, resp: httpx.Response) -> AsyncIterator[dict]:
        if self.response_mode == "sse":
            async for event in sse_events(resp):
                yield event
        elif self.response_mode == "ndjson":
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield payload
        else:  # "json": one document
            body = await resp.aread()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ProviderStreamError(f"{self.name}: non-JSON response", recoverable=True,
                                          provider=self.name, code="bad_response") from exc
            if isinstance(payload, dict):
                yield payload

    def estimate_usage(self, text, config, audio_seconds, usage) -> None:  # noqa: ANN001
        """Character-priced vendors need no estimate."""

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def strip_wav_header(chunk: bytes, first: bool) -> bytes:
    """Drop a canonical 44-byte RIFF header from the first chunk."""
    if first and chunk[:4] == b"RIFF":
        index = chunk.find(b"data")
        return chunk[index + 8:] if index >= 0 else chunk[44:]
    return chunk
