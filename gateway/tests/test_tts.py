"""TTS: adapters (OpenAI, Gemini) against httpx.MockTransport, audio
wrappers, resolver validation, and POST /v1/audio/speech end to end with the
usage event checked against the v2 contract (PLAN-tts-live.md §3.0).

Upstream payload shapes follow the vendors' documented streaming formats;
they are NOT yet live-captured (no keys on the build server) — see
docs/providers/openai.md and gemini.md "TTS" sections."""

import array
import base64
import json
import math

import httpx
import pytest
from fastapi.testclient import TestClient

from speechrouter_gateway.audio.mp3_frames import Mp3DurationCounter
from speechrouter_gateway.audio.pcm_codec import PcmConverter, wav_header
from speechrouter_gateway.config import Settings
from speechrouter_gateway.providers.base import ProviderStreamError, TTSConfig, TTSUsage
from speechrouter_gateway.providers.gemini import tts as gemini_tts
from speechrouter_gateway.providers.openai import tts as openai_tts
from speechrouter_gateway.router.catalog import Catalog
from speechrouter_gateway.router.resolver import ResolveError, TTSRequest, resolve_tts

PCM_1S = array.array(
    "h", [int(8000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(24000)]
).tobytes()


def _sse(*events: dict) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


async def _collect(adapter, text, config, usage) -> bytes:
    out = b""
    async for chunk in adapter.synthesize(text, config, usage):
        out += chunk
    return out


# ------------------------------------------------------------- OpenAI


async def test_openai_sse_decodes_audio_and_reads_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, content=_sse(
            {"type": "speech.audio.delta", "audio": base64.b64encode(b"\x01\x02").decode()},
            {"type": "speech.audio.delta", "audio": base64.b64encode(b"\x03").decode()},
            {"type": "speech.audio.done",
             "usage": {"input_tokens": 7, "output_tokens": 120, "total_tokens": 127}},
        ), headers={"content-type": "text/event-stream"})

    adapter = openai_tts.OpenAITTS("sk-house", "https://api.openai.com/v1",
                                   httpx.MockTransport(handler))
    usage = TTSUsage()
    config = TTSConfig(model="gpt-4o-mini-tts", voice="coral", format="pcm",
                       instructions="calm")
    audio = await _collect(adapter, "Hello there", config, usage)
    await adapter.close()

    assert audio == b"\x01\x02\x03"
    assert seen["auth"] == "Bearer sk-house"
    assert seen["body"]["stream_format"] == "sse"
    assert seen["body"]["instructions"] == "calm"
    assert usage.characters == len("Hello there")
    assert usage.tokens == {"text_input_tokens": 7, "audio_output_tokens": 120}


async def test_openai_tts1_streams_raw_bytes_without_sse():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "stream_format" not in body and body["speed"] == 1.5
        return httpx.Response(200, content=b"ID3mp3bytes")

    adapter = openai_tts.OpenAITTS("k", "https://x/v1", httpx.MockTransport(handler))
    usage = TTSUsage()
    config = TTSConfig(model="tts-1", voice="alloy", format="mp3", speed=1.5)
    assert await _collect(adapter, "abc", config, usage) == b"ID3mp3bytes"
    assert usage.tokens == {} and usage.characters == 3


@pytest.mark.parametrize("status,code,recoverable", [
    (400, "invalid_request", False), (401, "auth", False), (429, "rate_limited", True),
    (503, "upstream_5xx", True),
])
async def test_openai_http_errors_map_to_codes(status, code, recoverable):
    adapter = openai_tts.OpenAITTS(
        "k", "https://x/v1",
        httpx.MockTransport(lambda r: httpx.Response(status, json={"error": {"message": "no"}})),
    )
    with pytest.raises(ProviderStreamError) as info:
        await _collect(adapter, "a", TTSConfig(model="tts-1", voice="alloy", format="mp3"),
                       TTSUsage())
    assert info.value.code == code and info.value.recoverable is recoverable


def test_openai_provider_params_cannot_override_owned_fields():
    body = openai_tts.build_body(
        "hi", TTSConfig(model="tts-1", voice="alloy", format="mp3",
                        provider_params={"voice": "evil", "extra": 1}))
    assert body["voice"] == "alloy" and body["extra"] == 1


# ------------------------------------------------------------- Gemini


def _gemini_chunk(pcm: bytes, usage: dict | None = None) -> dict:
    chunk: dict = {"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;codec=pcm;rate=24000",
        "data": base64.b64encode(pcm).decode()}}]}}]}
    if usage:
        chunk["usageMetadata"] = usage
    return chunk


async def test_gemini_streams_pcm_reads_usage_and_hides_key_from_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(
            _gemini_chunk(PCM_1S[:24000]),
            _gemini_chunk(PCM_1S[24000:], {"promptTokenCount": 9,
                                           "candidatesTokenCount": 25}),
        ))

    adapter = gemini_tts.GeminiTTS("g-house", "https://generativelanguage.googleapis.com",
                                   httpx.MockTransport(handler))
    usage = TTSUsage()
    config = TTSConfig(model="gemini-3.8-flash-tts", voice="Puck", format="pcm",
                       instructions="Say cheerfully", language="en-US")
    audio = await _collect(adapter, "Have a nice day", config, usage)

    assert audio == PCM_1S
    assert seen["url"].endswith("/v1beta/models/gemini-3.8-flash-tts:streamGenerateContent?alt=sse")
    assert "key=" not in seen["url"] and seen["key"] == "g-house"
    gen = seen["body"]["generationConfig"]
    assert gen["responseModalities"] == ["AUDIO"]
    assert gen["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Puck"
    assert gen["speechConfig"]["languageCode"] == "en-US"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "Say cheerfully: Have a nice day"
    assert usage.tokens == {"text_input_tokens": 9, "audio_output_tokens": 25}
    assert not usage.estimated


async def test_gemini_estimates_when_usage_never_arrives():
    adapter = gemini_tts.GeminiTTS(
        "k", "https://g", httpx.MockTransport(lambda r: httpx.Response(
            200, content=_sse(_gemini_chunk(PCM_1S)))))
    usage = TTSUsage()
    await _collect(adapter, "x" * 40, TTSConfig(model="m", voice="Kore", format="pcm"), usage)
    assert usage.estimated
    assert usage.tokens == {"text_input_tokens": 10, "audio_output_tokens": 25}  # 1 s


def test_gemini_multispeaker_replaces_single_voice():
    multi = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": []}}
    body = gemini_tts.build_body("hi", TTSConfig(
        model="m", voice="Kore", format="pcm", provider_params={"speechConfig": multi}))
    speech = body["generationConfig"]["speechConfig"]
    assert "voiceConfig" not in speech and "multiSpeakerVoiceConfig" in speech


# ------------------------------------------------------------- codecs


def test_wav_header_is_streaming_riff():
    header = wav_header(24000)
    assert len(header) == 44 and header[:4] == b"RIFF" and header[8:16] == b"WAVEfmt "
    assert header[4:8] == b"\xff\xff\xff\xff" and header[40:44] == b"\xff\xff\xff\xff"


def test_wav_converter_prepends_header_once_and_handles_odd_splits():
    conv = PcmConverter("wav", 24000, 24000)
    out = conv.feed(PCM_1S[:1001]) + conv.feed(PCM_1S[1001:]) + conv.flush()
    assert out[:4] == b"RIFF" and out[44:] == PCM_1S


def test_g711_reference_vectors():
    from speechrouter_gateway.audio.pcm_codec import _linear_to_alaw, _linear_to_ulaw

    assert [_linear_to_ulaw(x) for x in (0, 32767, -32768)] == [0xFF, 0x80, 0x00]
    assert [_linear_to_alaw(x) for x in (0, 32767, -32768)] == [0xD5, 0xAA, 0x2A]


def _tone(freq: float, rate: int = 24000, seconds: float = 0.5) -> bytes:
    n = int(rate * seconds)
    return array.array(
        "h", [int(10000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    ).tobytes()


def _rms(pcm: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(pcm)
    body = samples[100:-100]
    return math.sqrt(sum(s * s for s in body) / len(body))


def test_decimator_passes_voice_band_and_rejects_aliases():
    def down(pcm: bytes) -> bytes:
        conv = PcmConverter("pcm", 24000, 8000)
        # odd split sizes exercise sample + window carry-over
        return b"".join(conv.feed(pcm[i:i + 777]) for i in range(0, len(pcm), 777))

    conv = PcmConverter("pcm", 24000, 8000)
    tone = _tone(440)
    low = b"".join(conv.feed(tone[i:i + 777]) for i in range(0, len(tone), 777)) + conv.flush()
    assert len(low) == len(tone) // 3  # exact: no head/tail lost to filter delay
    assert _rms(low) > 0.9 * _rms(_tone(440))
    assert _rms(down(_tone(7000))) < 0.1 * _rms(_tone(7000))  # above 4 kHz Nyquist


def test_mulaw_converter_one_byte_per_output_sample():
    conv = PcmConverter("mulaw", 24000, 8000)
    assert len(conv.feed(PCM_1S) + conv.flush()) == 8000


def _mp3_frames(header: bytes, length: int, count: int) -> bytes:
    return (header + b"\x00" * (length - 4)) * count


def test_mp3_counter_counts_frames_across_chunks_and_skips_id3():
    # MPEG-1 L3 128 kbps 44.1 kHz -> 417-byte frames of 1152 samples
    stream = b"ID3\x04\x00\x00\x00\x00\x00\x05" + b"tagxx" + _mp3_frames(
        b"\xff\xfb\x90\x00", 417, 10)
    counter = Mp3DurationCounter()
    for i in range(0, len(stream), 100):
        counter.feed(stream[i:i + 100])
    assert abs(counter.seconds - 10 * 1152 / 44100) < 1e-9

    # MPEG-2 L3 64 kbps 24 kHz -> 192-byte frames of 576 samples (OpenAI's mp3 rate)
    counter = Mp3DurationCounter()
    counter.feed(_mp3_frames(b"\xff\xf3\x84\x00", 192, 50))
    assert abs(counter.seconds - 50 * 576 / 24000) < 1e-9


# ------------------------------------------------------------- resolver


@pytest.fixture()
def keyed() -> Settings:
    return Settings(openai_api_key="o", gemini_api_key="g", _env_file=None)


def test_resolve_maps_formats_to_native_or_wrapper(keyed):
    catalog = Catalog.load()
    mp3 = resolve_tts("openai/gpt-4o-mini-tts", TTSRequest(format="mp3"), keyed, catalog)
    assert mp3.config.format == "mp3" and not mp3.wrap
    assert mp3.config.voice == "alloy" and mp3.content_type == "audio/mpeg"

    wav = resolve_tts("gemini/gemini-3.8-flash-tts", TTSRequest(format="wav"), keyed, catalog)
    assert wav.config.format == "pcm" and wav.wrap and wav.config.voice == "Kore"

    ulaw = resolve_tts("openai/tts-1", TTSRequest(format="mulaw"), keyed, catalog)
    assert ulaw.wrap and ulaw.out_sample_rate == 8000 and ulaw.config.format == "pcm"
    assert ulaw.content_type == "audio/PCMU;rate=8000;channels=1"

    pcm8k = resolve_tts("openai/tts-1", TTSRequest(format="pcm", sample_rate=8000), keyed,
                        catalog)
    assert pcm8k.wrap and pcm8k.config.format == "pcm"


@pytest.mark.parametrize("slug,request_kw,code", [
    ("openai/tts-1", {"voice": "marin"}, "invalid_request"),  # mini-tts-only voice
    ("openai/tts-1", {"instructions": "calm"}, "unsupported_capability"),
    ("gemini/gemini-3.8-flash-tts", {"format": "pcm", "speed": 1.2}, "unsupported_capability"),
    ("gemini/gemini-3.8-flash-tts", {"format": "mp3"}, "unsupported_encoding"),
    ("openai/tts-1", {"format": "pcm", "sample_rate": 16000}, "unsupported_encoding"),
    ("openai/tts-1", {"format": "mp3", "sample_rate": 8000}, "invalid_request"),
    ("openai/tts-1", {"speed": 9.0}, "invalid_request"),
    ("openai/tts-1", {"text_length": 5000}, "payload_too_large"),
    ("deepgram/nova-3", {}, "model_not_found"),
    ("openai/nope", {}, "model_not_found"),
])
def test_resolve_rejects(keyed, slug, request_kw, code):
    with pytest.raises(ResolveError) as info:
        resolve_tts(slug, TTSRequest(**request_kw), keyed, Catalog.load())
    assert info.value.code.value == code


def test_default_format_is_mp3_or_wav_for_pcm_only_models(keyed):
    catalog = Catalog.load()
    assert resolve_tts("openai/tts-1", TTSRequest(), keyed, catalog).out_format == "mp3"
    gemini = resolve_tts("gemini/gemini-3.8-flash-tts", TTSRequest(), keyed, catalog)
    assert gemini.out_format == "wav" and gemini.content_type == "audio/wav"


def test_resolve_requires_credentials():
    with pytest.raises(ResolveError) as info:
        resolve_tts("openai/tts-1", TTSRequest(), Settings(_env_file=None), Catalog.load())
    assert "credentials" in info.value.message


# ------------------------------------------------------------- endpoint


class CaptureEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


V2_FIELDS = {
    "session_id", "key_id", "model", "kind", "audio_seconds", "billed_seconds",
    "billing_basis", "characters", "provider_switches", "status", "byok", "ts", "units",
    "units_estimated", "parent_session_id", "session_seconds", "output_audio_seconds",
    "list_cost_usd",
}


@pytest.fixture()
def api(monkeypatch):
    from speechrouter_gateway.auth import build_keystore
    from speechrouter_gateway.config import KeyStoreKind
    from speechrouter_gateway.main import app

    state = {"mode": "ok"}

    def openai_handler(request: httpx.Request) -> httpx.Response:
        if state["mode"] == "fail":
            return httpx.Response(500, text="boom: our account balance is low")
        body = json.loads(request.content)
        if body["model"] == "tts-1":
            return httpx.Response(200, content=PCM_1S)
        return httpx.Response(200, content=_sse(
            {"type": "speech.audio.delta", "audio": base64.b64encode(PCM_1S).decode()},
            {"type": "speech.audio.done", "usage": {"input_tokens": 4, "output_tokens": 50}},
        ))

    monkeypatch.setattr(openai_tts, "TRANSPORT", httpx.MockTransport(openai_handler))
    with TestClient(app) as client:
        app.state.settings = app.state.settings.model_copy(update={
            "keys": "sk_test", "keystore": KeyStoreKind.local, "openai_api_key": "sk-house",
        })
        app.state.keystore = build_keystore(app.state.settings)
        app.state.catalog = Catalog.load()
        app.state.emitter = CaptureEmitter()
        yield client, app, state


AUTH = {"Authorization": "Bearer sk_test"}


def test_speech_streams_audio_and_emits_v2_usage(api):
    client, app, _ = api
    with client.stream("POST", "/v1/audio/speech", headers=AUTH, json={
        "model": "openai/gpt-4o-mini-tts", "input": "Hello", "voice": "coral",
        "response_format": "mulaw",
    }) as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/PCMU;rate=8000;channels=1"
        assert response.headers["x-speechrouter-model"] == "openai/gpt-4o-mini-tts"
        body = response.read()
    assert len(body) == 8000  # 1 s of 24 kHz pcm upstream -> 8 kHz G.711
    (event,) = app.state.emitter.events
    payload = event.__dict__
    assert set(payload) == V2_FIELDS
    assert event.kind == "tts_batch" and event.status == "completed"
    assert event.session_id.startswith("tts_") and event.parent_session_id is None
    assert event.billing_basis == "units" and event.billed_seconds == 0
    assert event.characters == 5
    assert event.units == {"text_input_tokens": 4, "audio_output_tokens": 50}
    assert abs(event.list_cost_usd - (4 * 0.60 + 50 * 12.00) / 1e6) < 1e-9


def test_speech_per_character_model_bills_characters(api):
    client, app, _ = api
    r = client.post("/v1/audio/speech", headers=AUTH, json={
        "model": "openai/tts-1", "input": "abcdefghij", "response_format": "pcm",
        "stream": False,
    })
    assert r.status_code == 200 and r.content == PCM_1S
    assert r.headers["content-type"] == "audio/L16;rate=24000;channels=1"
    (event,) = app.state.emitter.events
    assert event.units == {"characters": 10}
    assert event.audio_seconds == 1.0 and event.output_audio_seconds == 1.0
    assert r.headers["x-speechrouter-cost-usd"] == f"{10 * 0.000015:.6f}"


def test_speech_provider_failure_is_502_unbilled_and_hides_vendor_text(api):
    client, app, state = api
    state["mode"] = "fail"
    r = client.post("/v1/audio/speech", headers=AUTH,
                    json={"model": "openai/tts-1", "input": "hi"})
    assert r.status_code == 502
    assert "balance" not in r.json()["error"]["message"]
    (event,) = app.state.emitter.events
    assert event.status == "provider_error" and event.units == {}


def test_speech_auth_validation_and_flag(api):
    client, app, _ = api
    assert client.post("/v1/audio/speech", json={"model": "openai/tts-1",
                                                 "input": "x"}).status_code == 401
    bad = client.post("/v1/audio/speech", headers=AUTH,
                      json={"model": "openai/tts-1", "input": "x", "voice": "nobody"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_request"
    empty = client.post("/v1/audio/speech", headers=AUTH,
                        json={"model": "openai/tts-1", "input": ""})
    assert empty.status_code == 400

    app.state.catalog = Catalog.load(disabled_kinds=frozenset({"tts"}))
    off = client.post("/v1/audio/speech", headers=AUTH,
                      json={"model": "openai/tts-1", "input": "x"})
    assert off.status_code == 404
    assert not app.state.emitter.events


# ---- review regressions ----


async def test_gemini_failed_request_bills_nothing():
    adapter = gemini_tts.GeminiTTS(
        "k", "https://g", httpx.MockTransport(lambda r: httpx.Response(503, text="overloaded")))
    usage = TTSUsage()
    with pytest.raises(ProviderStreamError):
        await _collect(adapter, "hello", TTSConfig(model="m", voice="Kore", format="pcm"), usage)
    assert usage.tokens == {} and not usage.estimated


async def test_speech_job_meters_and_closes_when_stream_never_iterated():
    """Client aborts after the first chunk, before Starlette iterates the
    body: the background backstop must still meter and close upstream."""
    from types import SimpleNamespace

    from speechrouter_gateway.api.speech import _SpeechJob

    closed = []

    class Adapter(openai_tts.OpenAITTS):
        async def close(self):
            closed.append(True)

    def handler(request):
        return httpx.Response(200, content=_sse(
            {"type": "speech.audio.delta", "audio": base64.b64encode(PCM_1S).decode()},
            {"type": "speech.audio.delta", "audio": base64.b64encode(PCM_1S).decode()},
            {"type": "speech.audio.done", "usage": {"input_tokens": 3, "output_tokens": 40}},
        ))

    settings = Settings(openai_api_key="o", _env_file=None)
    resolved = resolve_tts("openai/gpt-4o-mini-tts", TTSRequest(format="pcm"), settings,
                           Catalog.load())
    resolved = resolved.__class__(**{**resolved.__dict__, "build": lambda: Adapter(
        "o", "https://x/v1", httpx.MockTransport(handler))})
    emitter = CaptureEmitter()
    job = _SpeechJob(SimpleNamespace(emitter=emitter), resolved, "Hello", "tts_x", "k1", False)
    assert await job.first_chunk() == PCM_1S
    await job.finish("client_disconnect")  # what the BackgroundTask runs
    await job.finish("completed")  # idempotent
    (event,) = emitter.events
    assert event.status == "client_disconnect" and closed == [True]
    assert event.audio_seconds == 1.0  # only what was pulled
    assert event.units["audio_output_tokens"] > 0 and event.units_estimated
