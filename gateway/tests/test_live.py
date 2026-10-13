"""Live passthrough (OpenAI Realtime, Gemini Live) against a scripted fake
upstream: a real websockets server on localhost in its own thread, so the
gateway proxies over real sockets exactly as in production.

Frame shapes follow the vendors' documented protocols (OpenAI Realtime GA
events, Gemini BidiGenerateContent); not yet live-captured — no keys on the
build server (PLAN §6)."""

import base64
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve

from speechrouter_gateway.auth.keystore import KeyRecord
from speechrouter_gateway.live.meter import (
    GeminiLiveMeter,
    b64_len,
    openai_units,
)
from speechrouter_gateway.router.catalog import Catalog

ONE_SECOND_24K = base64.b64encode(b"\x00\x01" * 24000).decode()
HALF_SECOND_24K = base64.b64encode(b"\x00\x01" * 12000).decode()
ONE_SECOND_16K = base64.b64encode(b"\x00\x01" * 16000).decode()

OPENAI_USAGE = {
    "total_tokens": 300, "input_tokens": 120, "output_tokens": 180,
    "input_token_details": {"text_tokens": 20, "audio_tokens": 100, "image_tokens": 0,
                            "cached_tokens": 30,
                            "cached_tokens_details": {"text_tokens": 10, "audio_tokens": 20}},
    "output_token_details": {"text_tokens": 30, "audio_tokens": 150},
}


# ------------------------------------------------------------- meter units


def test_b64_len_matches_decoded_length():
    for n in range(0, 10):
        assert b64_len(base64.b64encode(b"x" * n).decode()) == n


def test_openai_units_split_cached_out():
    assert openai_units(OPENAI_USAGE) == {
        "text_input_tokens": 10, "cached_text_input_tokens": 10,
        "audio_input_tokens": 80, "cached_audio_input_tokens": 20,
        "text_output_tokens": 30, "audio_output_tokens": 150,
    }


def test_gemini_units_by_modality_and_fallback():
    meter = GeminiLiveMeter()
    units = meter.gemini_units({
        "promptTokenCount": 130, "responseTokenCount": 75, "thoughtsTokenCount": 5,
        "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": 100},
                                {"modality": "TEXT", "tokenCount": 30}],
        "cacheTokensDetails": [{"modality": "TEXT", "tokenCount": 10}],
        "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 75}],
    })
    assert units == {"audio_input_tokens": 100, "text_input_tokens": 20,
                     "cached_text_input_tokens": 10, "audio_output_tokens": 75,
                     "text_output_tokens": 5}
    assert not meter.split_guessed
    assert meter.gemini_units({"promptTokenCount": 9, "responseTokenCount": 4}) == {
        "audio_input_tokens": 9, "audio_output_tokens": 4}
    assert meter.split_guessed


def test_gemini_cumulative_semantics_keeps_max():
    meter = GeminiLiveMeter("cumulative")
    for total in (10, 25, 40):
        meter.on_server(json.dumps({"usageMetadata": {
            "promptTokenCount": total,
            "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": total}]}}))
    assert meter.totals.units == {"audio_input_tokens": 40}
    summed = GeminiLiveMeter()
    for total in (10, 25, 40):
        summed.on_server(json.dumps({"usageMetadata": {
            "promptTokenCount": total,
            "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": total}]}}))
    assert summed.totals.units == {"audio_input_tokens": 75}


# ------------------------------------------------------------- fake upstream


class FakeUpstream:
    """Each test sets `script(conn)`; requests/frames are recorded."""

    def __init__(self):
        self.script = None
        self.requests: list = []  # (path, headers)
        self.received: list = []
        self.closed_with = None
        self._server = serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.socket.getsockname()[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def _handle(self, conn):
        self.requests.append((conn.request.path, dict(conn.request.headers)))
        try:
            self.script(conn, self)
        except Exception:  # noqa: BLE001 - client went away mid-script
            pass

    def recv(self, conn, timeout=5):
        frame = conn.recv(timeout=timeout)
        self.received.append(frame)
        return frame

    def stop(self):
        self._server.shutdown()


@pytest.fixture(scope="module")
def upstream():
    server = FakeUpstream()
    yield server
    server.stop()


class CaptureEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class FakeRedis:
    def __init__(self, kv=None):
        self.kv = kv or {}

    async def get(self, key):
        return self.kv.get(key)


class OrgKeyStore:
    """Cloud-like keystore: sk_test belongs to org 7, with a fake redis."""

    def __init__(self, redis):
        self.redis = redis

    async def lookup(self, key):
        return KeyRecord(key_id="k1", org_id="7") if key == "sk_test" else None


@pytest.fixture()
def gw(upstream):
    from speechrouter_gateway.main import app
    from speechrouter_gateway.router.limits import ConcurrencyGuard

    upstream.received.clear()
    upstream.requests.clear()
    with TestClient(app) as client:
        app.state.settings = app.state.settings.model_copy(update={
            "openai_api_key": "sk-house", "gemini_api_key": "g-house",
            "openai_base_url": f"http://127.0.0.1:{upstream.port}/v1",
            "gemini_base_url": f"http://127.0.0.1:{upstream.port}",
            "live_checkpoint_seconds": 600, "live_min_balance_microusd": 5_000_000,
            "max_concurrent_live": 5,
        })
        app.state.keystore = OrgKeyStore(FakeRedis({"speechrouter:balance:7": "50000000"}))
        app.state.catalog = Catalog.load()
        app.state.emitter = CaptureEmitter()
        app.state.live_concurrency = ConcurrencyGuard(limit=5)
        yield client, app


def _wait(predicate, limit=5.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


def _leave(ws, app, count=1):
    """Close like a client would and wait for the session's final usage
    while the TestClient portal is still alive."""
    ws.close(1000)
    _wait(lambda: len(app.state.emitter.events) >= count
          and app.state.emitter.events[-1].status != "in_progress")


OPENAI_URL = "/v1/realtime?model=openai/gpt-realtime-2.1"
BEARER = {"Authorization": "Bearer sk_test"}


def openai_conversation(conn, up):
    conn.send(json.dumps({"type": "session.created", "session": {
        "model": "gpt-realtime-2.1",
        "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                            "transcription": {"model": "gpt-4o-mini-transcribe"}},
                  "output": {"format": {"type": "audio/pcm", "rate": 24000}}}}}))
    while True:
        frame = up.recv(conn)
        if isinstance(frame, bytes):
            conn.send(b"binary-echo")
            continue
        if json.loads(frame)["type"] == "response.create":
            break
    conn.send(json.dumps({"type": "response.output_audio.delta", "delta": HALF_SECOND_24K}))
    conn.send(json.dumps({"type": "response.done",
                          "response": {"status": "completed", "usage": OPENAI_USAGE}}))
    up.recv(conn, timeout=10)  # wait for the client to leave


# ------------------------------------------------------------- OpenAI


def test_openai_passthrough_forwards_verbatim_and_meters(gw, upstream):
    client, app = gw
    upstream.script = openai_conversation
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        assert json.loads(ws.receive_text())["type"] == "session.created"
        append = json.dumps({"type": "input_audio_buffer.append", "audio": ONE_SECOND_24K})
        ws.send_text(append)
        ws.send_bytes(b"\x01\x02")
        assert ws.receive_bytes() == b"binary-echo"
        ws.send_text(json.dumps({"type": "response.create"}))
        assert json.loads(ws.receive_text())["type"] == "response.output_audio.delta"
        assert json.loads(ws.receive_text())["type"] == "response.done"
        _leave(ws, app, count=2)

    path, headers = upstream.requests[0]
    assert path == "/v1/realtime?model=gpt-realtime-2.1"
    assert headers["authorization"] == "Bearer sk-house"  # ours, never the client's
    assert append in upstream.received and b"\x01\x02" in upstream.received

    live, stt = app.state.emitter.events
    assert live.kind == "live" and live.model == "openai/gpt-realtime-2.1"
    assert live.session_id == f"{live.parent_session_id}:1" and live.status == "completed"
    assert live.parent_session_id.startswith("live_")
    assert live.audio_seconds == 1.0 and live.output_audio_seconds == 0.5
    assert live.billing_basis == "units" and not live.units_estimated
    assert live.units == openai_units(OPENAI_USAGE)
    expected = (10 * 4 + 10 * 0.4 + 80 * 32 + 20 * 0.4 + 30 * 24 + 150 * 64) / 1e6
    assert abs(live.list_cost_usd - expected) < 1e-9
    # OpenAI bills input transcription separately: companion STT leg
    assert stt.kind == "stt_stream" and stt.model == "openai/gpt-4o-mini-transcribe"
    assert stt.session_id == f"{live.parent_session_id}:t1"
    assert stt.billed_seconds == 1.0 and stt.parent_session_id == live.parent_session_id
    assert stt.list_cost_usd > 0


def test_openai_browser_subprotocol_auth_and_bare_model(gw, upstream):
    client, app = gw
    upstream.script = openai_conversation
    with client.websocket_connect(
        "/v1/realtime?model=gpt-realtime-2.1",
        subprotocols=["realtime", "openai-insecure-api-key.sk_test"],
    ) as ws:
        assert ws.accepted_subprotocol == "realtime"
        assert json.loads(ws.receive_text())["type"] == "session.created"
        _leave(ws, app)
    _, headers = upstream.requests[0]
    assert "sk_test" not in json.dumps(headers)


def test_openai_session_update_cannot_switch_model(gw, upstream):
    client, app = gw

    def script(conn, up):
        conn.send(json.dumps({"type": "session.created", "session": {}}))
        up.recv(conn, timeout=10)

    upstream.script = script
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "session.update",
                                 "session": {"model": "gpt-realtime-mini"}}))
        error = json.loads(ws.receive_text())
        assert error["type"] == "error" and error["error"]["code"] == "invalid_request"
        _leave(ws, app)
    assert not any("session.update" in str(f) for f in upstream.received)


@pytest.mark.parametrize("url,headers,code", [
    (OPENAI_URL, {}, "auth_failed"),
    ("/v1/realtime?model=openai/gpt-nope", BEARER, "model_not_found"),
    ("/v1/realtime?model=gemini/gemini-3.8-live", BEARER, "model_not_found"),
    ("/v1/realtime", BEARER, "invalid_request"),
])
def test_openai_rejections_are_native_error_events(gw, url, headers, code):
    client, app = gw
    with client.websocket_connect(url, headers=headers) as ws:
        event = json.loads(ws.receive_text())
        assert event["type"] == "error" and event["error"]["code"] == code
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_text()
        assert info.value.code == 1008
    assert not app.state.emitter.events


def test_min_balance_and_blocked_org(gw):
    client, app = gw
    app.state.keystore.redis.kv["speechrouter:balance:7"] = "4999999"
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        event = json.loads(ws.receive_text())
        assert event["error"]["code"] == "insufficient_credits"
        assert "$5.00" in event["error"]["message"]
    app.state.keystore.redis.kv["speechrouter:blocked:7"] = "1"
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        assert json.loads(ws.receive_text())["error"]["code"] == "insufficient_credits"


def test_byok_skips_min_balance_and_uses_org_key(gw, upstream):
    client, app = gw
    app.state.keystore.redis.kv.update({
        "speechrouter:balance:7": "0", "speechrouter:byok:7:openai": "sk-org-own"})
    upstream.script = openai_conversation
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        assert json.loads(ws.receive_text())["type"] == "session.created"
        _leave(ws, app)
    assert upstream.requests[0][1]["authorization"] == "Bearer sk-org-own"
    assert app.state.emitter.events[0].byok and app.state.emitter.events[0].list_cost_usd == 0


def test_live_concurrency_cap(gw, upstream):
    client, app = gw
    from speechrouter_gateway.router.limits import ConcurrencyGuard

    app.state.live_concurrency = ConcurrencyGuard(limit=1)
    upstream.script = openai_conversation
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as first:
        first.receive_text()
        with client.websocket_connect(OPENAI_URL, headers=BEARER) as second:
            assert json.loads(second.receive_text())["error"]["code"] == "concurrency_exceeded"
        _leave(first, app)
        _wait(lambda: app.state.live_concurrency.active("7") == 0)


def test_upstream_close_propagates_with_sanitized_account_reason(gw, upstream):
    client, app = gw

    def script(conn, up):
        conn.send(json.dumps({"type": "session.created", "session": {}}))
        conn.close(code=1011, reason="You exceeded your current quota")

    upstream.script = script
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        ws.receive_text()
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_text()
        _wait(lambda: app.state.emitter.events)
    assert info.value.code == 1011 and "quota" not in (info.value.reason or "")
    assert app.state.emitter.events[0].status == "provider_error"


def test_house_key_account_errors_are_rewritten_in_band(gw, upstream):
    client, app = gw

    def script(conn, up):
        conn.send(json.dumps({"type": "error", "error": {
            "type": "insufficient_quota", "code": "insufficient_quota",
            "message": "You exceeded your current quota, org-abc123"}}))
        conn.send(json.dumps({"type": "error", "error": {
            "type": "invalid_request_error", "code": "invalid_value",
            "message": "Invalid value: 'pcm17'"}}))
        up.recv(conn, timeout=10)

    upstream.script = script
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        account = json.loads(ws.receive_text())
        assert account["error"]["code"] == "provider_error"
        assert "org-abc123" not in json.dumps(account)
        assert json.loads(ws.receive_text())["error"]["message"] == "Invalid value: 'pcm17'"
        _leave(ws, app)


def test_checkpoints_emit_deltas_with_contiguous_seq(gw, upstream):
    client, app = gw
    app.state.settings = app.state.settings.model_copy(update={"live_checkpoint_seconds": 1})

    def script(conn, up):
        conn.send(json.dumps({"type": "session.created", "session": {}}))
        up.recv(conn)
        conn.send(json.dumps({"type": "response.done", "response": {"usage": OPENAI_USAGE}}))
        up.recv(conn, timeout=10)

    upstream.script = script
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "input_audio_buffer.append", "audio": ONE_SECOND_24K}))
        ws.receive_text()
        _wait(lambda: len(app.state.emitter.events) >= 2, limit=4)
        _leave(ws, app, count=3)
    events = [e for e in app.state.emitter.events if e.kind == "live"]
    parent = events[0].parent_session_id
    assert [e.session_id for e in events] == [f"{parent}:{i}" for i in
                                              range(1, len(events) + 1)]
    assert all(e.status == "in_progress" for e in events[:-1])
    assert events[-1].status == "completed"
    # deltas: the usage is counted exactly once across all events
    total: dict = {}
    for event in events:
        for key, value in event.units.items():
            total[key] = total.get(key, 0) + value
    assert total == openai_units(OPENAI_USAGE)
    assert sum(e.audio_seconds for e in events) == 1.0


def test_no_usage_reported_estimates_final_event(gw, upstream):
    client, app = gw

    def script(conn, up):
        conn.send(json.dumps({"type": "session.created", "session": {}}))
        up.recv(conn)
        conn.send(json.dumps({"type": "response.output_audio.delta", "delta": ONE_SECOND_24K}))
        up.recv(conn, timeout=10)

    upstream.script = script
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        ws.receive_text()
        ws.send_text(json.dumps({"type": "input_audio_buffer.append", "audio": ONE_SECOND_24K}))
        ws.receive_text()
        _leave(ws, app)
    (event,) = app.state.emitter.events
    assert event.units_estimated
    assert event.units == {"audio_input_tokens": 10, "audio_output_tokens": 20}


def test_idle_live_session_times_out(gw, upstream):
    client, app = gw
    app.state.settings = app.state.settings.model_copy(update={"live_idle_timeout_seconds": 1})

    def script(conn, up):
        conn.send(json.dumps({"type": "session.created", "session": {}}))
        up.recv(conn, timeout=10)

    upstream.script = script
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        ws.receive_text()
        assert json.loads(ws.receive_text())["error"]["code"] == "audio_timeout"
        _wait(lambda: app.state.emitter.events)
    assert app.state.emitter.events[0].status == "audio_timeout"


def test_live_flag_off_means_model_not_found(gw):
    client, app = gw
    app.state.catalog = Catalog.load(disabled_kinds=frozenset({"live"}))
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        assert json.loads(ws.receive_text())["error"]["code"] == "model_not_found"


def test_upstream_handshake_rejection_is_provider_error(gw, upstream):
    client, app = gw
    app.state.settings = app.state.settings.model_copy(update={
        "openai_base_url": "http://127.0.0.1:9/v1"})  # nothing listens on port 9
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        assert json.loads(ws.receive_text())["error"]["code"] == "provider_error"
        _wait(lambda: app.state.emitter.events)
    assert app.state.emitter.events[0].status == "provider_error"
    assert app.state.emitter.events[0].units == {}


# ------------------------------------------------------------- Gemini

GEMINI_PATH = "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
SETUP = json.dumps({"setup": {"model": "models/gemini-3.8-live",
                              "generationConfig": {"responseModalities": ["AUDIO"]}}})


def gemini_conversation(conn, up):
    assert json.loads(up.recv(conn))["setup"]["model"] == "models/gemini-3.8-live"
    conn.send(json.dumps({"setupComplete": {}}).encode())  # Gemini frames are binary
    up.recv(conn)  # realtimeInput audio
    for _ in range(2):
        conn.send(json.dumps({
            "serverContent": {"modelTurn": {"parts": [{"inlineData": {
                "mimeType": "audio/pcm;rate=24000", "data": HALF_SECOND_24K}}]}},
            "usageMetadata": {
                "promptTokenCount": 40, "responseTokenCount": 13,
                "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": 40}],
                "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 13}]},
        }).encode())
    conn.send(json.dumps({"serverContent": {"turnComplete": True}}).encode())
    up.recv(conn, timeout=10)


def test_gemini_passthrough_first_frame_model_and_usage(gw, upstream):
    client, app = gw
    upstream.script = gemini_conversation
    with client.websocket_connect(f"{GEMINI_PATH}?key=sk_test") as ws:
        ws.send_text(SETUP)
        assert json.loads(ws.receive_bytes()) == {"setupComplete": {}}
        ws.send_text(json.dumps({"realtimeInput": {"audio": {
            "mimeType": "audio/pcm;rate=16000", "data": ONE_SECOND_16K}}}))
        for _ in range(3):
            ws.receive_bytes()
        _leave(ws, app)

    path, headers = upstream.requests[0]
    assert path == GEMINI_PATH and "key=" not in path  # key never in the upstream URL
    assert headers["x-goog-api-key"] == "g-house"
    assert upstream.received[0] == SETUP  # forwarded unchanged

    (event,) = app.state.emitter.events
    assert event.model == "gemini/gemini-3.8-live" and event.kind == "live"
    assert event.audio_seconds == 1.0 and event.output_audio_seconds == 1.0
    assert event.units == {"audio_input_tokens": 80, "audio_output_tokens": 26}
    assert abs(event.list_cost_usd - (80 * 3.00 + 26 * 12.00) / 1e6) < 1e-12


@pytest.mark.parametrize("path,kw", [
    (GEMINI_PATH, {"headers": {"x-goog-api-key": "sk_test"}}),
    ("/v1/live/gemini?access_token=sk_test", {}),
    (GEMINI_PATH.replace("v1beta", "v1alpha") + "Constrained", {
        "headers": {"Authorization": "Token sk_test"}}),
])
def test_gemini_auth_forms_and_paths(gw, upstream, path, kw):
    client, app = gw
    upstream.script = gemini_conversation
    with client.websocket_connect(path, **kw) as ws:
        ws.send_text(SETUP)
        assert json.loads(ws.receive_bytes()) == {"setupComplete": {}}
        _leave(ws, app)
    version = "v1alpha" if "v1alpha" in path else "v1beta"
    assert version in upstream.requests[0][0]


def test_gemini_rejections_close_with_reason(gw):
    client, _ = gw
    with client.websocket_connect(f"{GEMINI_PATH}?key=wrong") as ws:
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_bytes()
    assert info.value.code == 1008 and info.value.reason.startswith("auth_failed")

    with client.websocket_connect(f"{GEMINI_PATH}?key=sk_test") as ws:
        ws.send_text(json.dumps({"setup": {"model": "models/gpt-realtime-2.1"}}))
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_bytes()
    assert info.value.reason.startswith("model_not_found")

    with client.websocket_connect(f"{GEMINI_PATH}?key=sk_test") as ws:
        ws.send_text(json.dumps({"clientContent": {}}))
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_bytes()
    assert info.value.reason.startswith("invalid_request")


def test_gemini_second_setup_closes_session(gw, upstream):
    client, app = gw
    upstream.script = gemini_conversation
    with client.websocket_connect(f"{GEMINI_PATH}?key=sk_test") as ws:
        ws.send_text(SETUP)
        ws.receive_bytes()
        ws.send_text(SETUP)
        with pytest.raises(WebSocketDisconnect) as info:
            while True:
                ws.receive_bytes()
        _wait(lambda: app.state.emitter.events)
    assert info.value.code == 1008
    assert app.state.emitter.events[0].status == "error"


# ------------------------------------------------------------- client secrets


def test_realtime_client_secrets_alias_mints_connectable_token(gw, upstream):
    client, app = gw
    r = client.post("/v1/realtime/client_secrets", headers=BEARER,
                    json={"expires_after": {"anchor": "created_at", "seconds": 600},
                          "session": {"type": "realtime", "model": "gpt-realtime-2.1"}})
    assert r.status_code == 200
    body = r.json()
    assert body["value"].startswith("st_") and body["session"]["model"] == "gpt-realtime-2.1"
    assert body["expires_at"] - time.time() <= 301  # clamped to MAX_TTL

    upstream.script = openai_conversation
    with client.websocket_connect(
        OPENAI_URL, subprotocols=["realtime", f"openai-insecure-api-key.{body['value']}"]
    ) as ws:
        assert json.loads(ws.receive_text())["type"] == "session.created"
        _leave(ws, app)


# ---- review regressions ----


def test_gemini_cached_tokens_not_double_counted_without_details():
    meter = GeminiLiveMeter()
    units = meter.gemini_units({"promptTokenCount": 1000, "responseTokenCount": 10,
                                "cacheTokensDetails": [{"modality": "AUDIO", "tokenCount": 800}]})
    assert units == {"cached_audio_input_tokens": 800, "audio_input_tokens": 200,
                     "audio_output_tokens": 10}


def test_client_secrets_tolerates_non_object_expires_after(gw):
    client, _ = gw
    r = client.post("/v1/realtime/client_secrets", headers=BEARER, json={"expires_after": 60})
    assert r.status_code == 200 and r.json()["value"].startswith("st_")


def test_gemini_dial_failure_closes_1008_with_reason_and_meters(gw):
    client, app = gw
    app.state.settings = app.state.settings.model_copy(update={
        "gemini_base_url": "http://127.0.0.1:9"})
    with client.websocket_connect(f"{GEMINI_PATH}?key=sk_test") as ws:
        ws.send_text(SETUP)
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_bytes()
        _wait(lambda: app.state.emitter.events)
    assert info.value.code == 1008 and info.value.reason.startswith("provider_error")
    assert app.state.emitter.events[0].status == "provider_error"


def _bare_session(entry_slug="openai/gpt-realtime-2.1", emitter=None):
    from types import SimpleNamespace

    from speechrouter_gateway.config import Settings
    from speechrouter_gateway.live.dialects import OPENAI
    from speechrouter_gateway.live.proxy import LiveSession, ResolvedLive

    catalog = Catalog.load()
    settings = Settings(_env_file=None, openai_api_key="x")
    resolved = ResolvedLive(slug=entry_slug, model=entry_slug.split("/")[1],
                            entry=catalog.find(entry_slug), settings=settings)
    return LiveSession(SimpleNamespace(), OPENAI, resolved, emitter or CaptureEmitter(),
                       catalog, "k1", settings)


async def test_credit_accrual_excludes_already_emitted_checkpoints():
    session = _bare_session()
    session.meter.on_server(json.dumps({"type": "response.done",
                                        "response": {"usage": OPENAI_USAGE}}))
    before = session.accrued_usd()
    assert before > 0
    await session._emit(final=False)  # checkpoint -> debited by cloud
    assert session.accrued_usd() == 0
    session.meter.on_server(json.dumps({"type": "response.done",
                                        "response": {"usage": OPENAI_USAGE}}))
    assert abs(session.accrued_usd() - before) < 1e-12


async def test_checkpoint_write_survives_cancellation():
    import asyncio

    class SlowEmitter(CaptureEmitter):
        async def emit(self, event):
            await asyncio.sleep(0.05)
            self.events.append(event)

    emitter = SlowEmitter()
    session = _bare_session(emitter=emitter)
    session.meter.on_server(json.dumps({"type": "response.done",
                                        "response": {"usage": OPENAI_USAGE}}))
    task = asyncio.create_task(session._emit(final=False))
    await asyncio.sleep(0.01)
    task.cancel()  # e.g. the watchdog is cancelled as the client hangs up
    await asyncio.sleep(0.1)
    (event,) = emitter.events
    assert event.units == openai_units(OPENAI_USAGE) and event.session_id.endswith(":1")


# ---- cloud-session requests (SRC-TTS-LIVE) ----


def test_cloud_published_live_floor_overrides_setting(gw):
    client, app = gw
    kv = app.state.keystore.redis.kv
    kv["speechrouter:balance:7"] = "20000000"  # $20, above the $5 setting
    kv["speechrouter:live_min_balance"] = "25000000"  # cloud says $25
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        event = json.loads(ws.receive_text())
        assert event["error"]["code"] == "insufficient_credits"
        assert "$25.00" in event["error"]["message"]


def test_gemini_accepts_bearer_subprotocol(gw, upstream):
    client, app = gw
    upstream.script = gemini_conversation
    with client.websocket_connect("/v1/live/gemini", subprotocols=["bearer", "sk_test"]) as ws:
        assert ws.accepted_subprotocol == "bearer"
        ws.send_text(SETUP)
        assert json.loads(ws.receive_bytes()) == {"setupComplete": {}}
        _leave(ws, app)
    assert "sk_test" not in json.dumps(upstream.requests[0][1])


def test_models_include_disabled_for_price_sync(gw):
    client, app = gw
    app.state.catalog = Catalog.load(disabled_kinds=frozenset({"tts", "live"}))
    public = client.get("/v1/models").json()["data"]
    assert {m["kind"] for m in public} == {"stt"}
    full = {m["slug"]: m for m in client.get("/v1/models?include_disabled=true").json()["data"]}
    assert full["openai/gpt-realtime-2.1"]["enabled"] is False
    assert full["gemini/gemini-3.8-flash-tts"]["pricing"]["per_1m_audio_output_tokens_usd"] == 9.0
    assert "enabled" not in full["deepgram/nova-3"]
    # still not routable
    with client.websocket_connect(OPENAI_URL, headers=BEARER) as ws:
        assert json.loads(ws.receive_text())["error"]["code"] == "model_not_found"


def test_openai_cached_image_tokens_split_out():
    units = openai_units({"input_token_details": {
        "image_tokens": 100, "cached_tokens": 40,
        "cached_tokens_details": {"image_tokens": 40}}})
    assert units == {"image_input_tokens": 60, "cached_image_input_tokens": 40}


def test_cors_exposes_speechrouter_headers(gw):
    client, _ = gw
    r = client.get("/v1/models", headers={"Origin": "https://app.example"})
    exposed = r.headers.get("access-control-expose-headers", "").lower()
    assert "x-speechrouter-cost-usd" in exposed and "x-speechrouter-request-id" in exposed


def test_gemini_live_real_per_turn_usage_sums_and_bills_unlisted_prompt_tokens():
    """Two real turns (2026-10-13): one usageMetadata per turn, response does
    not accumulate (44 -> 47) while the prompt re-bills context (559 -> 628).
    Details (TEXT+AUDIO) sum short of promptTokenCount: remainder is billed."""
    meter = GeminiLiveMeter()  # per_message default
    turns = [
        {"promptTokenCount": 559, "responseTokenCount": 44, "totalTokenCount": 603,
         "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 312},
                                 {"modality": "AUDIO", "tokenCount": 222}],
         "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 44}],
         "thoughtsTokenCount": 49},
        {"promptTokenCount": 628, "responseTokenCount": 47, "totalTokenCount": 675,
         "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 323},
                                 {"modality": "AUDIO", "tokenCount": 266}],
         "responseTokensDetails": [{"modality": "AUDIO", "tokenCount": 47}],
         "thoughtsTokenCount": 31},
    ]
    for meta in turns:
        meter.on_server(json.dumps({"usageMetadata": meta}))
    units = meter.totals.units
    assert units["audio_input_tokens"] == 222 + 266
    assert units["text_input_tokens"] == (312 + 25) + (323 + 39)  # incl. unlisted remainder
    assert units["audio_output_tokens"] == 44 + 47
    assert units["text_output_tokens"] == 49 + 31  # thinking billed as text output
    total_in = units["audio_input_tokens"] + units["text_input_tokens"]
    assert total_in == 559 + 628  # every prompt token billed exactly once
