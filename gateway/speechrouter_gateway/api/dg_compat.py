"""Deepgram-compatible wire mode.

Point an unmodified official Deepgram SDK at this gateway and it works —
against ANY provider, with mid-stream failover. The dialect is selected by
the auth scheme Deepgram SDKs use (`Authorization: Token <key>` header, or
the browser `['token', <key>]` WebSocket subprotocol); native clients keep
speaking our protocol on the same paths.

Wire truth: docs/providers/deepgram.md (primary-source protocol brief).

Mappings worth knowing:
- `model=nova-3` -> `deepgram/nova-3`; a full slug (`soniox/stt-rt-v5`)
  routes anywhere. `fallbacks` is honored as our extra param.
- Our finals are endpointer-driven utterance finals, so Results carry
  `is_final: true, speech_final: true` together.
- `CloseStream` -> our finalize (flush -> final Results -> Metadata -> close),
  `KeepAlive` -> keepalive. Mid-stream `Finalize` has no session-preserving
  equivalent here yet: acknowledged as a no-op.
- Errors close the socket with DG-style close codes instead of JSON.
"""

import json
from typing import Any

from fastapi import Request, WebSocket

from ..protocol.events import Code
from ..router.resolver import StreamRequest
from ..router.session import SessionClosed

# our error codes -> WS close codes the way Deepgram fails
_CLOSE_CODES = {
    Code.auth_failed: 1008,
    Code.key_revoked: 1008,
    Code.insufficient_credits: 1008,
    Code.concurrency_exceeded: 1008,
    Code.invalid_request: 1008,
    Code.model_not_found: 1008,
    Code.unsupported_capability: 1008,
    Code.unsupported_encoding: 1008,
}


def dg_ws_credentials(websocket: WebSocket) -> str | None:
    """Deepgram SDK auth: `Authorization: Token <key>` or ['token', key]
    subprotocol. Returning a key means the client speaks Deepgram."""
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("token "):
        return header[6:].strip()
    parts = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    if len(parts) == 2 and parts[0] == "token":
        return parts[1]
    return None


def dg_http_credentials(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("token "):
        return header[6:].strip()
    return None


def resolve_model(raw: str) -> str:
    """Bare Deepgram model names stay Deepgram; full slugs route anywhere."""
    return raw if "/" in raw else f"deepgram/{raw}"


_DG_PASSTHROUGH = (
    "punctuate", "smart_format", "endpointing", "utterance_end_ms", "vad_events",
    "filler_words", "numerals", "profanity_filter", "redact", "diarize_model",
    "multichannel", "no_delay", "dictation", "measurements",
)


def translate_params(params: Any) -> tuple[str, list[str], StreamRequest]:
    """Deepgram query params -> (slug, fallbacks, StreamRequest)."""
    slug = resolve_model(params.get("model", "") or "")
    fallbacks = [
        resolve_model(s.strip()) for s in params.get("fallbacks", "").split(",") if s.strip()
    ]

    terms: list[str] = []
    getlist = getattr(params, "getlist", None)
    if getlist:
        terms.extend(t for t in getlist("keyterm") if t)
        # keywords come as word:boost — the boost is Deepgram-internal
        terms.extend(k.split(":", 1)[0] for k in getlist("keywords") if k)

    provider_params: dict[str, Any] = {}
    if slug.startswith("deepgram/"):
        for name in _DG_PASSTHROUGH:
            if params.get(name) is not None:
                provider_params[name] = params.get(name)

    request = StreamRequest(
        encoding=params.get("encoding", "linear16"),
        sample_rate=int(params.get("sample_rate", "16000")),
        channels=int(params.get("channels", "1")),
        language=params.get("language"),
        # Deepgram's default is false — honor the dialect's expectations
        interim_results=(params.get("interim_results", "false").lower() == "true"),
        diarization=(
            params.get("diarize", "false").lower() == "true"
            or params.get("diarize_model") is not None
        ),
        keyterms=tuple(terms),
        include_raw=False,
        provider_params=provider_params,
    )
    return slug, fallbacks, request


def dg_words(words: list | None) -> list[dict]:
    out = []
    for w in words or []:
        entry: dict[str, Any] = {
            "word": w.w,
            "start": w.start,
            "end": w.end,
            "confidence": w.conf if w.conf is not None else 1.0,
            "punctuated_word": w.w,
        }
        if w.speaker is not None:
            entry["speaker"] = w.speaker
        if w.lang is not None:
            entry["language"] = w.lang
        out.append(entry)
    return out


class DGTransport:
    """Wraps the raw WebSocket as our ClientTransport, translating both
    directions so STTSession never knows the client speaks Deepgram."""

    def __init__(self, websocket: WebSocket, model_label: str):
        self._ws = websocket
        self._model = model_label
        self._request_id = ""

    # ---- inbound: audio passes through, DG control -> our control -------

    async def recv(self) -> bytes | str | None:
        while True:
            try:
                message = await self._ws.receive()
            except RuntimeError:
                return None
            if message["type"] == "websocket.disconnect":
                return None
            data = message.get("bytes")
            if data is not None:
                return data
            text = message.get("text") or ""
            try:
                kind = json.loads(text).get("type")
            except (json.JSONDecodeError, AttributeError):
                continue
            if kind == "CloseStream":
                return json.dumps({"type": "finalize"})
            if kind == "KeepAlive":
                return json.dumps({"type": "keepalive"})
            # Mid-stream Finalize: no session-preserving flush yet — ack-drop.
            continue

    # ---- outbound: our events -> DG messages ----------------------------

    async def send_event(self, event: Any) -> None:
        kind = getattr(event, "type", "")
        payload: dict[str, Any] | None = None

        if kind == "session.open":
            self._request_id = event.session_id
            return  # Deepgram sends nothing on open
        elif kind == "transcript":
            start = event.start or 0.0
            duration = (event.end - start) if (event.end is not None) else 0.0
            payload = {
                "type": "Results",
                "channel_index": [0, 1],
                "start": round(start, 3),
                "duration": round(max(duration, 0.0), 3),
                "is_final": event.is_final,
                "speech_final": event.is_final,
                "from_finalize": False,
                "channel": {
                    "alternatives": [
                        {
                            "transcript": event.text,
                            "confidence": 1.0,
                            "words": dg_words(event.words),
                        }
                    ]
                },
                "metadata": {
                    "request_id": self._request_id,
                    "model_info": {"name": self._model},
                },
            }
        elif kind == "speech_started":
            payload = {"type": "SpeechStarted", "channel": [0, 1], "timestamp": event.at}
        elif kind == "utterance_end":
            payload = {"type": "UtteranceEnd", "channel": [0, 1], "last_word_end": event.at}
        elif kind == "done":
            payload = {
                "type": "Metadata",
                "request_id": self._request_id,
                "created": "",
                "duration": getattr(event.usage, "audio_seconds", 0.0) or 0.0,
                "channels": 1,
                "models": [self._model],
            }
        elif kind == "error":
            # v1 Deepgram signals errors via close codes, not JSON
            try:
                await self._ws.close(
                    code=_CLOSE_CODES.get(event.code, 1011), reason=str(event.message)[:120]
                )
            except Exception as exc:
                raise SessionClosed() from exc
            raise SessionClosed()
        else:
            return  # provider_switched etc: invisible magic by design

        try:
            await self._ws.send_text(json.dumps(payload))
        except Exception as exc:
            raise SessionClosed() from exc


def dg_batch_response(transcript: Any, model_label: str, request_id: str) -> dict:
    """Our Transcript -> Deepgram prerecorded response shape."""
    return {
        "metadata": {
            "request_id": request_id,
            "created": "",
            "duration": transcript.end or 0.0,
            "channels": 1,
            "models": [model_label],
        },
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": transcript.text,
                            "confidence": 1.0,
                            "words": dg_words(transcript.words),
                        }
                    ]
                }
            ]
        },
    }
