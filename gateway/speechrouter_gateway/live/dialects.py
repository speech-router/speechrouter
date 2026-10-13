"""Per-provider halves of the live passthrough (PLAN §2.2, §2.5).

Each dialect answers: where are the client's credentials, which model does
the client want (and when do we know it), how do we dial upstream with OUR
key, and how does a gateway error look in that provider's own protocol so
the vendor SDK surfaces it normally.

Client credentials are never forwarded upstream, and the upstream key never
reaches the client: the upstream URL/headers are built from Settings only.
"""

import json
import uuid
from urllib.parse import quote

from fastapi import WebSocket

from ..config import Settings
from .meter import GeminiLiveMeter, LiveMeter, OpenAIRealtimeMeter, parse_frame


def _ws_base(http_base: str) -> str:
    if http_base.startswith("https://"):
        return "wss://" + http_base[len("https://"):]
    if http_base.startswith("http://"):
        return "ws://" + http_base[len("http://"):]
    return http_base


def _offered(websocket: WebSocket) -> list[str]:
    header = websocket.headers.get("sec-websocket-protocol", "")
    return [p.strip() for p in header.split(",") if p.strip()]


def _bearer(websocket: WebSocket) -> str:
    header = websocket.headers.get("authorization", "")
    for scheme in ("bearer ", "token "):
        if header.lower().startswith(scheme):
            return header[len(scheme):].strip()
    return ""


class Dialect:
    name: str
    provider: str
    in_band_errors: bool = False  # True: errors are JSON events; False: close frames only

    def credentials(self, websocket: WebSocket) -> str:
        raise NotImplementedError

    def accept_subprotocol(self, websocket: WebSocket) -> str | None:
        return None

    def model_from_url(self, websocket: WebSocket) -> str | None:
        """Model known at upgrade time, or None if it arrives in a frame."""
        return None

    def model_from_first_frame(self, frame: str | bytes) -> str | None:
        return None

    def slug(self, model: str) -> str:
        return model if model.startswith(f"{self.provider}/") else f"{self.provider}/{model}"

    def upstream(self, settings: Settings, websocket: WebSocket, model: str
                 ) -> tuple[str, dict[str, str]]:
        raise NotImplementedError

    def meter(self, settings: Settings, model: str) -> LiveMeter:
        raise NotImplementedError

    def error_frame(self, code: str, message: str) -> str | None:
        """An in-band error event, or None if this protocol only has close."""
        return None


class OpenAIRealtime(Dialect):
    """`WSS /v1/realtime?model=...` — the OpenAI SDKs' own path under
    base_url=<gateway>/v1. Auth: `Authorization: Bearer`, the browser
    subprotocol `openai-insecure-api-key.<key>`, our `bearer,<key>`, or
    ?api_key=."""

    name = "openai-realtime"
    provider = "openai"
    in_band_errors = True

    def credentials(self, websocket: WebSocket) -> str:
        if key := _bearer(websocket):
            return key
        offered = _offered(websocket)
        for proto in offered:
            if proto.startswith("openai-insecure-api-key."):
                return proto[len("openai-insecure-api-key."):]
        if len(offered) == 2 and offered[0] == "bearer":
            return offered[1]
        return websocket.query_params.get("api_key", "")

    def accept_subprotocol(self, websocket: WebSocket) -> str | None:
        offered = _offered(websocket)
        if "realtime" in offered:
            return "realtime"
        if offered[:1] == ["bearer"]:
            return "bearer"
        return offered[0] if offered else None

    def model_from_url(self, websocket: WebSocket) -> str | None:
        return websocket.query_params.get("model", "")

    def upstream(self, settings, websocket, model):
        url = f"{_ws_base(settings.openai_base_url.rstrip('/'))}/realtime?model={quote(model)}"
        return url, {"Authorization": f"Bearer {settings.openai_api_key}"}

    def meter(self, settings, model):
        return OpenAIRealtimeMeter(model)

    def error_frame(self, code: str, message: str) -> str | None:
        return json.dumps({
            "type": "error",
            "event_id": f"event_sr_{uuid.uuid4().hex[:16]}",
            "error": {"type": "invalid_request_error", "code": code, "message": message,
                      "param": None, "event_id": None},
        })


class GeminiLive(Dialect):
    """The google-genai SDK's own path under http_options.base_url=<gateway>.
    Auth: ?key=, ?access_token= (ephemeral style), `x-goog-api-key`, or
    `Authorization: Bearer|Token`. The model arrives in the first frame
    (`setup.model = "models/<m>"`), so the gateway reads one frame before
    dialing and forwards it unchanged."""

    name = "gemini-live"
    provider = "gemini"

    def credentials(self, websocket: WebSocket) -> str:
        params = websocket.query_params
        return (
            params.get("key")
            or params.get("access_token")
            or websocket.headers.get("x-goog-api-key", "")
            or _bearer(websocket)
        )

    def model_from_first_frame(self, frame: str | bytes) -> str | None:
        payload = parse_frame(frame)
        setup = (payload or {}).get("setup")
        model = setup.get("model") if isinstance(setup, dict) else None
        if not isinstance(model, str) or not model:
            return None
        return model.removeprefix("models/")

    def upstream(self, settings, websocket, model):
        # v1alpha clients keep v1alpha upstream; everything else is v1beta
        version = "v1alpha" if "v1alpha" in websocket.url.path else "v1beta"
        base = _ws_base(settings.gemini_base_url.rstrip("/"))
        url = (f"{base}/ws/google.ai.generativelanguage.{version}"
               ".GenerativeService.BidiGenerateContent")
        return url, {"x-goog-api-key": settings.gemini_api_key}

    def meter(self, settings, model):
        return GeminiLiveMeter(settings.gemini_live_usage_semantics)


OPENAI = OpenAIRealtime()
GEMINI = GeminiLive()
