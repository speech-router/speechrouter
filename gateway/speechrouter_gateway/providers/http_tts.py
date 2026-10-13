"""Shared plumbing for HTTP-streaming TTS adapters (OpenAI, Gemini).

- One pooled httpx client per adapter instance; `transport` is injectable so
  tests run against httpx.MockTransport without a socket.
- SSE parsing: both vendors stream `data: {json}` lines.
- Error mapping: vendor status -> ProviderStreamError.code. 400s describe the
  caller's input (never our account state), so their message is safe to show;
  everything else is reported upstream and replaced by a customer-facing line.
"""

import json
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


def status_error(provider: str, status: int, body: str) -> ProviderStreamError:
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
