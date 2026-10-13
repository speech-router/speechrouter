"""xAI Grok TTS (docs/providers/tts/xai.md).

REST (batch /v1/audio/speech and fallback): POST /v1/tts, Bearer auth, body
{text, voice_id, language (required; "auto"), output_format{codec,
sample_rate}, speed?}; raw audio bytes back.

Native socket for /v1/speak: wss://api.x.ai/v1/tts?language=&voice=&codec=
&sample_rate= (config in the QUERY; Bearer header on upgrade).
  client: text.delta{delta} | text.done | text.clear
  server: audio.delta{delta: base64} | audio.done | audio.clear | error{message}
text.clear is barge-in; audio until audio.clear is stale and dropped here.
No model id exists: the catalog slug is xai/grok-tts. $15 / 1M characters.
"""

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx
import websockets
import websockets.exceptions

from ...config import Settings, tts_base_url
from ..base import (
    ProviderStreamError,
    TTSCapabilities,
    TTSConfig,
    TTSProvider,
    TTSStream,
    TTSUsage,
)
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts
from ..wsconnect import ws_connect

BASE = "https://api.x.ai"
RATES = frozenset({8000, 16000, 22050, 24000, 44100, 48000})

CAPABILITIES = TTSCapabilities(
    default_voice="eve",
    formats=frozenset({"pcm", "mp3", "mulaw", "alaw"}),
    sample_rates=RATES,
    format_rates={"mulaw": frozenset({8000, 16000}), "alaw": frozenset({8000, 16000})},
    max_input_chars=60000,
    speed=True,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("xai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "XaiTTS":
    if not settings.xai_api_key:
        raise ProviderNotConfigured("xai")
    return XaiTTS({"key": settings.xai_api_key,
                   "base": tts_base_url(settings, "xai", BASE)}, TRANSPORT)


def output_format(fmt: str, rate: int) -> dict:
    if fmt == "mp3":
        return {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000}
    return {"codec": fmt, "sample_rate": rate}


class XaiTTS(HTTPStreamTTS, TTSProvider):
    name = "xai"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        body: dict = {"text": text, "voice_id": config.voice,
                      "language": config.language or "auto",
                      "output_format": output_format(config.format, config.sample_rate)}
        if config.speed is not None:
            body["speed"] = config.speed
        for key, value in config.provider_params.items():
            body.setdefault(key, value)
        return {"url": f"{self.credentials['base']}/v1/tts",
                "headers": {"Authorization": f"Bearer {self.credentials['key']}"},
                "json": body}

    def open_stream(self, config: TTSConfig) -> "XaiStream":
        return XaiStream(self.credentials)


class XaiStream(TTSStream):
    def __init__(self, credentials: dict):
        self._credentials = credentials
        self._ws: websockets.ClientConnection | None = None
        self.usage = TTSUsage()
        self._dropping = False
        self._cleared = asyncio.Event()
        self._done = False

    async def connect(self, config: TTSConfig) -> None:
        fmt = output_format(config.format, config.sample_rate)
        query = {"language": config.language or "auto", "voice": config.voice,
                 "codec": fmt["codec"], "sample_rate": fmt["sample_rate"]}
        if "bit_rate" in fmt:
            query["bit_rate"] = fmt["bit_rate"]
        if config.speed is not None:
            query["speed"] = config.speed
        base = self._credentials["base"].replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1)
        try:
            self._ws = await ws_connect(
                f"{base}/v1/tts?{urlencode(query)}",
                additional_headers={"Authorization": f"Bearer {self._credentials['key']}"},
                ping_interval=20, max_size=16 * 1024 * 1024)
        except websockets.exceptions.InvalidStatus as exc:
            status = exc.response.status_code
            raise ProviderStreamError(f"xai tts handshake HTTP {status}",
                                      recoverable=status >= 500, provider="xai",
                                      code="auth" if status in (401, 403) else f"http_{status}"
                                      ) from exc
        except (OSError, TimeoutError) as exc:
            raise ProviderStreamError(f"xai tts connect failed: {exc}", recoverable=True,
                                      provider="xai", code="connect_failed") from exc

    async def _send(self, payload: dict) -> None:
        assert self._ws is not None
        try:
            await self._ws.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed as exc:
            raise ProviderStreamError("xai tts socket closed", recoverable=False,
                                      provider="xai", code="closed") from exc

    async def send_text(self, text: str) -> None:
        self.usage.characters += len(text)
        await self._send({"type": "text.delta", "delta": text})

    async def clear(self, playback_ms: int | None = None) -> dict:
        self._dropping = True
        self._cleared.clear()
        await self._send({"type": "text.clear"})
        await self._cleared.wait()  # audio.clear observed by audio()
        return {}

    async def finish(self) -> None:
        await self._send({"type": "text.done"})
        self._done = True

    async def audio(self) -> AsyncIterator[bytes]:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                event = json.loads(raw) if isinstance(raw, str) else {}
                kind = event.get("type")
                if kind == "audio.delta":
                    if self._dropping:
                        continue
                    data = event.get("delta")
                    if data:
                        yield base64.b64decode(data)
                elif kind == "audio.clear":
                    self._dropping = False
                    self._cleared.set()
                elif kind == "audio.done":
                    if self._done:
                        return  # final utterance flushed
                elif kind == "error":
                    raise ProviderStreamError(f"xai tts error: {event.get('message')}",
                                              recoverable=False, provider="xai",
                                              code="stream_error")
        except websockets.exceptions.ConnectionClosed as exc:
            if not self._done:
                raise ProviderStreamError("xai tts socket closed mid-stream",
                                          recoverable=False, provider="xai",
                                          code="closed") from exc
        finally:
            self._cleared.set()  # never leave a clear() waiting

    async def close(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
