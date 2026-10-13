"""Deepgram Aura TTS: POST /v1/speak (docs/providers/tts/deepgram.md).

- `Authorization: Token`; body {"text"} (max 2000 chars); everything else is
  query: model (= the VOICE, e.g. aura-2-thalia-en), encoding, container,
  sample_rate. Chunked raw audio back; `dg-char-count` reports billed chars.
- Catalog slugs are the families (deepgram/aura-2, deepgram/aura-1,
  deepgram/flux); the request's `voice` is the full Deepgram model id
  (aura-2-thalia-en, flux-haley-en). Billed per character.

Flux TTS (docs/providers/tts/deepgram-flux.md): batch on POST /v2/speak (same
query shape, no `container`); /v1/speak uses the native socket
wss://api.deepgram.com/v2/speak — binary audio frames, JSON control:
  client: Speak{text} | Flush | Interrupt{playback_offset{type:time_ms,value}} | Close
  server: Connected | SpeechStarted | Flushed | SpeechMetadata{billable_character_count}
          | SpeechInterrupted{text_spoken?, text_remaining?} | SessionMetadata | Error
Interrupt is barge-in: audio until SpeechInterrupted is stale and dropped.
"""

import asyncio
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

BASE = "https://api.deepgram.com"

CAPABILITIES = TTSCapabilities(
    default_voice="aura-2-thalia-en",  # per-family defaults live in the catalog
    formats=frozenset({"pcm", "mp3", "opus", "flac", "aac", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000, 24000, 32000, 44100, 48000}),
    format_rates={"mulaw": frozenset({8000, 16000}), "alaw": frozenset({8000, 16000})},
    max_input_chars=2000,
)

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("deepgram", capabilities=CAPABILITIES)
def build(settings: Settings) -> "DeepgramTTS":
    if not settings.deepgram_api_key:
        raise ProviderNotConfigured("deepgram")
    return DeepgramTTS({"key": settings.deepgram_api_key,
                        "base": tts_base_url(settings, "deepgram", BASE)}, TRANSPORT)


def is_flux(config: TTSConfig) -> bool:
    return config.model == "flux"


def query(fmt: str, rate: int, voice: str, flux: bool = False) -> dict:
    params: dict = {"model": voice}
    if fmt in {"pcm", "mulaw", "alaw"}:
        params.update(encoding="linear16" if fmt == "pcm" else fmt, sample_rate=rate)
        if not flux:
            params["container"] = "none"
    elif fmt == "opus":
        params.update(encoding="opus", container="ogg")
    else:  # mp3 / flac / aac: fixed rates server-side
        params["encoding"] = fmt
    return params


class DeepgramTTS(HTTPStreamTTS, TTSProvider):
    name = "deepgram"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        flux = is_flux(config)
        return {
            "url": f"{self.credentials['base']}/{'v2' if flux else 'v1'}/speak",
            "params": {**query(config.format, config.sample_rate, config.voice, flux),
                       **config.provider_params},
            "headers": {"Authorization": f"Token {self.credentials['key']}"},
            "json": {"text": text},
        }

    def on_headers(self, headers, usage):
        count = headers.get("dg-char-count")
        if count and count.isdigit():
            usage.characters = int(count)  # Deepgram's own billed count wins

    def open_stream(self, config: TTSConfig) -> "FluxStream | None":
        # Flux streams raw samples only; compressed formats stay on REST
        if is_flux(config) and config.format in {"pcm", "mulaw", "alaw"}:
            return FluxStream(self.credentials)
        return None


class FluxStream(TTSStream):
    def __init__(self, credentials: dict):
        self._credentials = credentials
        self._ws: websockets.ClientConnection | None = None
        self.usage = TTSUsage()
        self._dropping = False
        self._interrupted = asyncio.Event()
        self._interrupt_info: dict = {}
        self._finishing = False
        self._bytes_per_ms = 48.0  # set at connect from encoding/rate
        self._sent_ms = 0.0
        self._last_offset = -1
        self._session_billed: int | None = None
        self._turn_billed = 0

    async def connect(self, config: TTSConfig) -> None:
        params = query(config.format, config.sample_rate, config.voice, flux=True)
        if config.speed is not None:
            params["speed"] = config.speed
        params.update(config.provider_params)
        width = 2 if config.format == "pcm" else 1
        self._bytes_per_ms = config.sample_rate * width / 1000
        base = self._credentials["base"].replace("https://", "wss://", 1).replace(
            "http://", "ws://", 1)
        try:
            self._ws = await ws_connect(
                f"{base}/v2/speak?{urlencode(params)}",
                additional_headers={"Authorization": f"Token {self._credentials['key']}"},
                ping_interval=20, max_size=16 * 1024 * 1024)
        except websockets.exceptions.InvalidStatus as exc:
            status = exc.response.status_code
            raise ProviderStreamError(f"deepgram flux handshake HTTP {status}",
                                      recoverable=status >= 500, provider="deepgram",
                                      code="auth" if status in (401, 403) else f"http_{status}"
                                      ) from exc
        except (OSError, TimeoutError) as exc:
            raise ProviderStreamError(f"deepgram flux connect failed: {exc}", recoverable=True,
                                      provider="deepgram", code="connect_failed") from exc

    async def _send(self, payload: dict) -> None:
        assert self._ws is not None
        try:
            await self._ws.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed as exc:
            raise ProviderStreamError("deepgram flux socket closed", recoverable=False,
                                      provider="deepgram", code="closed") from exc

    async def send_text(self, text: str) -> None:
        self.usage.characters += len(text)
        await self._send({"type": "Speak", "text": text})

    async def clear(self, playback_ms: int | None = None) -> dict:
        offset = int(playback_ms if playback_ms is not None else self._sent_ms)
        offset = max(offset, self._last_offset + 1)  # Flux: must advance per interrupt
        self._last_offset = offset
        self._dropping = True
        self._interrupted.clear()
        await self._send({"type": "Interrupt",
                          "playback_offset": {"type": "time_ms", "value": offset}})
        await self._interrupted.wait()
        return dict(self._interrupt_info)

    async def finish(self) -> None:
        self._finishing = True
        await self._send({"type": "Flush"})
        await self._send({"type": "Close"})

    async def audio(self) -> AsyncIterator[bytes]:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    if self._dropping:
                        continue
                    self._sent_ms += len(raw) / self._bytes_per_ms
                    yield raw
                    continue
                event = json.loads(raw)
                kind = event.get("type")
                if kind == "SpeechInterrupted":
                    self._interrupt_info = {k: event[k] for k in ("text_spoken",
                                                                  "text_remaining")
                                            if isinstance(event.get(k), str)}
                    self._dropping = False
                    self._interrupted.set()
                elif kind == "SpeechMetadata":
                    billed = event.get("billable_character_count")
                    if isinstance(billed, int):
                        self._turn_billed += billed
                elif kind == "SessionMetadata":
                    billed = event.get("total_billable_character_count")
                    if isinstance(billed, int):
                        self._session_billed = billed
                    if self._finishing:
                        return
                elif kind == "Error":
                    raise ProviderStreamError(
                        f"deepgram flux error {event.get('code')}: {event.get('description')}",
                        recoverable=False, provider="deepgram", code=str(event.get("code")))
        except websockets.exceptions.ConnectionClosed as exc:
            if not self._finishing:
                raise ProviderStreamError("deepgram flux socket closed mid-stream",
                                          recoverable=False, provider="deepgram",
                                          code="closed") from exc
        finally:
            self._interrupted.set()
            # Deepgram's billed count beats our count of characters sent
            billed = self._session_billed if self._session_billed is not None else (
                self._turn_billed or None)
            if billed:
                self.usage.characters = billed

    async def close(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
