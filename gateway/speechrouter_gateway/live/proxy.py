"""Live passthrough session: client WS <-> provider WS (PLAN §2.3-2.6).

  client ──(up: client->provider)──▶ provider
  client ◀──(down: provider->client)── provider
         watchdog: duration, idle, credits, usage checkpoints

Frames are forwarded as received (text stays text, binary stays binary);
the meter only reads them. No queues between the pumps: `await send()` on
one side is the backpressure for reads on the other.

Usage: one `kind=live` event per `live_checkpoint_seconds` with the delta
since the previous one (status in_progress), then a final event with the
terminal status. session_id = <parent>:<seq>, seq from 1 with no gaps.
OpenAI input transcription (billed separately by OpenAI at the
transcription model's rate) rides as companion `kind=stt_stream` events,
session_id = <parent>:t<n>. Contract: PLAN-tts-live.md §3.0.
"""

import asyncio
import contextlib
import re
import time
import uuid
from dataclasses import dataclass

import websockets
import websockets.exceptions
from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ..alerting import customer_facing, report_provider_failure
from ..config import Settings
from ..logging import logger
from ..metering import UsageEmitter, UsageEvent
from ..protocol.events import Code
from ..providers.wsconnect import ws_connect
from ..router.catalog import Catalog, price_units
from .dialects import Dialect
from .meter import LiveTotals, parse_frame

MAX_FRAME_BYTES = 16 * 1024 * 1024  # OpenAI accepts large conversation items (images)
CREDIT_CHECK_SECONDS = 30
# House-key upstream messages that would expose OUR account state. Anything
# else (bad setup field, invalid event) is the client's to debug and passes.
_ACCOUNT_HINTS = re.compile(
    r"quota|billing|credit|balance|api[ _-]?key|permission|unauthori[sz]ed|"
    r"exceeded your|account|organization|project",
    re.IGNORECASE,
)
_ACCOUNT_CODES = {"insufficient_quota", "invalid_api_key", "account_deactivated",
                  "billing_hard_limit_reached", "billing_not_active", "unauthorized"}
_SENDABLE_CLOSE = {1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013}


@dataclass(frozen=True)
class ResolvedLive:
    slug: str
    model: str  # provider-native
    entry: dict
    settings: Settings  # BYOK-swapped copy when byok


class LiveLimit(Exception):
    def __init__(self, code: Code, status: str, message: str):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


class _ClientGone(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


class _UpstreamGone(Exception):
    def __init__(self, code: int | None, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


def _close_code(code: int | None, default: int = 1011) -> int:
    if code is None:
        return default
    return code if code in _SENDABLE_CLOSE or 3000 <= code <= 4999 else default


class LiveSession:
    def __init__(
        self,
        websocket: WebSocket,
        dialect: Dialect,
        resolved: ResolvedLive,
        emitter: UsageEmitter,
        catalog: Catalog,
        key_id: str,
        settings: Settings,
        byok: bool = False,
        org_id: str | None = None,
        redis=None,
        first_frame: str | bytes | None = None,
    ):
        self._ws = websocket
        self._dialect = dialect
        self._resolved = resolved
        self._emitter = emitter
        self._catalog = catalog
        self._key_id = key_id
        self._settings = settings
        self._byok = byok
        self._org_id = org_id
        self._redis = redis
        self._first_frame = first_frame
        self.parent_id = f"live_{uuid.uuid4().hex[:16]}"
        self.meter = dialect.meter(settings, resolved.model)
        self._upstream: websockets.ClientConnection | None = None
        self._started = time.monotonic()
        self._last_activity = time.monotonic()
        self._emitted = LiveTotals()
        self._emitted_at = self._started
        self._seq = 0
        self._tseq = 0
        self._status = "completed"
        self._client_close: tuple[int, str] = (1000, "")

    # ----------------------------------------------------------- lifecycle

    async def run(self) -> None:
        tasks: set[asyncio.Task] = set()
        try:
            await self._dial()
            tasks = {
                asyncio.create_task(self._pump_up(), name="up"),
                asyncio.create_task(self._pump_down(), name="down"),
                asyncio.create_task(self._watchdog(), name="watchdog"),
            }
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            exc = next(iter(done)).exception()
            if exc is not None:
                raise exc
        except _ClientGone as gone:
            self._status = "completed" if gone.code in (1000, 1001, 1005) else \
                "client_disconnect"
            self._client_close = (1000, "")
        except _UpstreamGone as gone:
            self._on_upstream_close(gone)
        except LiveLimit as exc:
            self._status = exc.status
            await self._reject_client(exc.code.value, exc.message)
        except Exception:
            self._status = "error"
            logger.error("live session crashed", exc_info=True,
                         extra={"session": self.parent_id})
            await self._reject_client(Code.internal_error.value, "internal error", close=1011)
        finally:
            # every path — failed dial included — closes both sides and meters
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._close_upstream(1000)
            await self._close_client(*self._client_close)
            await self._emit_final()

    async def _dial(self) -> None:
        url, headers = self._dialect.upstream(self._resolved.settings, self._ws,
                                              self._resolved.model)
        beta = self._ws.headers.get("openai-beta")
        if self._dialect.provider == "openai":
            offered = self._ws.headers.get("sec-websocket-protocol", "")
            if "openai-beta.realtime-v1" in offered:
                beta = "realtime=v1"
            if beta:
                headers["OpenAI-Beta"] = beta  # protocol version, not a credential
        try:
            self._upstream = await ws_connect(
                url, additional_headers=headers, max_size=MAX_FRAME_BYTES,
                compression=None, ping_interval=20, ping_timeout=60,
            )
        except websockets.exceptions.InvalidStatus as exc:
            status = exc.response.status_code
            body = (exc.response.body or b"").decode(errors="replace")[:300]
            report_provider_failure(self._dialect.provider, self._resolved.slug,
                                    f"handshake HTTP {status}: {body}", code=f"http_{status}")
            message = (f"provider rejected the connection (HTTP {status}): {body}"
                       if self._byok else customer_facing(None))
            raise LiveLimit(Code.provider_error, "provider_error", message) from exc
        except (OSError, TimeoutError, websockets.exceptions.InvalidHandshake) as exc:
            report_provider_failure(self._dialect.provider, self._resolved.slug,
                                    f"connect failed: {exc}", code="connect_failed")
            raise LiveLimit(Code.provider_error, "provider_error",
                            customer_facing(None)) from exc
        if self._first_frame is not None:
            try:
                await self._upstream.send(self._first_frame)
            except websockets.exceptions.ConnectionClosed as exc:
                raise _UpstreamGone(*self._upstream_close(exc)) from exc
            self.meter.on_client(self._first_frame)
        logger.info("live session open", extra={
            "session": self.parent_id, "model": self._resolved.slug, "byok": self._byok,
            "dialect": self._dialect.name,
        })

    # --------------------------------------------------------------- pumps

    async def _pump_up(self) -> None:
        assert self._upstream is not None
        while True:
            message = await self._ws.receive()
            if message["type"] == "websocket.disconnect":
                raise _ClientGone(int(message.get("code") or 1005))
            self._last_activity = time.monotonic()
            frame = message.get("bytes")
            if frame is None:
                frame = message.get("text") or ""
            rejection = self.meter.on_client(frame)
            if rejection is not None:
                if not self._dialect.in_band_errors:  # close-only protocol
                    raise LiveLimit(Code.invalid_request, "error", rejection)
                await self._send_client_error(Code.invalid_request.value, rejection)
                continue
            try:
                await self._upstream.send(frame)
            except websockets.exceptions.ConnectionClosed as exc:
                raise _UpstreamGone(*self._upstream_close(exc)) from exc

    async def _pump_down(self) -> None:
        assert self._upstream is not None
        try:
            async for frame in self._upstream:
                self._last_activity = time.monotonic()
                self.meter.on_server(frame)
                frame = self._sanitize_down(frame)
                try:
                    if isinstance(frame, bytes):
                        await self._ws.send_bytes(frame)
                    else:
                        await self._ws.send_text(frame)
                except Exception as exc:  # noqa: BLE001 - client socket gone
                    raise _ClientGone(1006) from exc
        except websockets.exceptions.ConnectionClosed as exc:
            raise _UpstreamGone(*self._upstream_close(exc)) from exc
        assert self._upstream is not None
        raise _UpstreamGone(self._upstream.close_code, self._upstream.close_reason or "")

    def _upstream_close(self, exc: websockets.exceptions.ConnectionClosed
                        ) -> tuple[int | None, str]:
        frame = exc.rcvd
        return (frame.code, frame.reason) if frame is not None else (None, "")

    def _sanitize_down(self, frame: str | bytes) -> str | bytes:
        """House-key sessions: rewrite in-band provider errors that describe
        OUR account (quota, key) — reported to us, generic to the client."""
        if self._byok or self._dialect.provider != "openai" or isinstance(frame, bytes):
            return frame
        if '"error"' not in frame:
            return frame
        payload = parse_frame(frame)
        if not payload or payload.get("type") != "error":
            return frame
        error = payload.get("error") or {}
        code = str(error.get("code") or "")
        if code in _ACCOUNT_CODES or _ACCOUNT_HINTS.search(str(error.get("message") or "")):
            report_provider_failure("openai", self._resolved.slug, str(error), code=code)
            return self._dialect.error_frame(Code.provider_error.value,
                                             customer_facing(None)) or frame
        return frame

    def _on_upstream_close(self, gone: _UpstreamGone) -> None:
        code = gone.code
        reason = gone.reason or ""
        if code in (1000, 1001):
            self._status = "completed"
        else:
            self._status = "provider_error"
            report_provider_failure(self._dialect.provider, self._resolved.slug,
                                    f"upstream closed {code}: {reason}", code=f"close_{code}")
            if not self._byok and _ACCOUNT_HINTS.search(reason):
                reason = customer_facing(None)
        self._client_close = (_close_code(code), reason[:123])

    # ------------------------------------------------------------ watchdog

    async def _watchdog(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(1.0)
            tick += 1
            now = time.monotonic()
            if now - self._emitted_at >= self._settings.live_checkpoint_seconds:
                await self._emit_checkpoint()
            if tick % CREDIT_CHECK_SECONDS == 0:
                await self._check_credits()
            if now - self._started > self._settings.max_live_session_seconds:
                raise LiveLimit(Code.session_expired, "session_expired",
                                "maximum live session duration reached")
            if now - self._last_activity > self._settings.live_idle_timeout_seconds:
                raise LiveLimit(Code.audio_timeout, "audio_timeout",
                                "no traffic in either direction; closing idle session")

    def accrued_usd(self) -> float:
        """Cost not yet in an emitted event. Emitted checkpoints are debited
        by cloud and already reflected in speechrouter:balance — counting
        them again would cut sessions that still have credit. (Consumer lag
        of a few seconds can leave a checkpoint briefly uncounted; the 30 s
        check cadence already bounds overdraw at that scale.)"""
        if self.meter.reported:
            units = self.meter.totals.minus(self._emitted).units
        else:
            units = self.meter.estimate()  # never emitted: estimates land at close
        return price_units(self._resolved.entry, units)

    async def _check_credits(self) -> None:
        if self._byok or self._redis is None or not self._org_id:
            return
        try:
            raw = await self._redis.get(f"speechrouter:balance:{self._org_id}")
        except Exception:  # noqa: BLE001 - fail open
            return
        if raw is None:
            return
        if int(raw) - self.accrued_usd() * 1_000_000 <= 0:
            raise LiveLimit(Code.insufficient_credits, "insufficient_credits",
                            "credit balance exhausted mid-session — "
                            "top up at speechrouter.ai/settings/billing")

    # ---------------------------------------------------------- client I/O

    async def _send_client_error(self, code: str, message: str) -> None:
        frame = self._dialect.error_frame(code, message)
        if frame is not None and self._ws.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await self._ws.send_text(frame)

    async def _reject_client(self, code: str, message: str, close: int = 1008) -> None:
        await self._send_client_error(code, message)
        self._client_close = (close, f"{code}: {message}"[:123])

    async def _close_client(self, code: int, reason: str) -> None:
        if self._ws.application_state != WebSocketState.CONNECTED:
            return
        with contextlib.suppress(Exception):
            await self._ws.close(code=code, reason=reason)

    async def _close_upstream(self, code: int) -> None:
        if self._upstream is not None:
            with contextlib.suppress(Exception):
                await self._upstream.close(code=code)

    # --------------------------------------------------------------- usage

    async def _emit_checkpoint(self) -> None:
        await self._emit(final=False)

    async def _emit_final(self) -> None:
        await self._emit(final=True)

    async def _emit(self, final: bool) -> None:
        now = time.monotonic()
        current = self.meter.totals.copy()
        delta = current.minus(self._emitted)
        estimated = getattr(self.meter, "split_guessed", False)
        if final and not self.meter.reported and (
            current.audio_in_seconds or current.audio_out_seconds
        ):
            # provider never reported: estimate the whole session once, here
            delta.units = self.meter.estimate()
            estimated = True
        self._emitted = current
        interval = round(now - self._emitted_at, 3)
        self._emitted_at = now
        self._seq += 1
        status = self._status if final else "in_progress"
        entry = self._resolved.entry
        event = UsageEvent(
            session_id=f"{self.parent_id}:{self._seq}",
            key_id=self._key_id,
            model=self._resolved.slug,
            kind="live",
            audio_seconds=round(delta.audio_in_seconds, 3),
            billed_seconds=0.0,
            billing_basis="units",
            status=status,
            byok=self._byok,
            units={k: round(v, 3) for k, v in delta.units.items()},
            units_estimated=estimated,
            parent_session_id=self.parent_id,
            session_seconds=interval,
            output_audio_seconds=round(delta.audio_out_seconds, 3),
            list_cost_usd=0.0 if self._byok else round(price_units(entry, delta.units), 8),
        )
        events = [event]
        transcription = self.meter.transcription_model
        if transcription and delta.transcribed_seconds > 0:
            events.append(self._transcription_event(transcription, delta, status, interval))
        if final:
            logger.info("live session finished", extra={
                "session": self.parent_id, "model": self._resolved.slug, "status": status,
                "events": self._seq, "audio_in_seconds": round(current.audio_in_seconds, 3),
                "audio_out_seconds": round(current.audio_out_seconds, 3),
                "units": current.units, "estimated": estimated,
            })
        # shielded: _emitted/_seq already advanced, so a cancellation here
        # (client hangs up mid-checkpoint) must not drop the write
        await asyncio.shield(self._send_usage(events))

    async def _send_usage(self, events: list[UsageEvent]) -> None:
        for item in events:
            try:
                await self._emitter.emit(item)
            except Exception:  # noqa: BLE001 - metering never kills a session
                logger.error("live usage emit failed", exc_info=True)

    def _transcription_event(self, model: str, delta: LiveTotals, status: str,
                             interval: float) -> UsageEvent:
        self._tseq += 1
        slug = f"{self._dialect.provider}/{model}"
        seconds = round(delta.transcribed_seconds, 3)
        entry = self._catalog.find(slug) or {}
        per_second = float((entry.get("pricing") or {}).get("per_second_usd") or 0.0)
        return UsageEvent(
            session_id=f"{self.parent_id}:t{self._tseq}",
            key_id=self._key_id,
            model=slug,
            kind="stt_stream",
            audio_seconds=seconds,
            billed_seconds=seconds,
            billing_basis="audio_time",
            status=status,
            byok=self._byok,
            parent_session_id=self.parent_id,
            session_seconds=interval,
            list_cost_usd=0.0 if self._byok else round(seconds * per_second, 8),
        )
