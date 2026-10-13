"""Phase-2 TTS adapters against httpx.MockTransport (no keys, no network).

Each provider test pins the request contract from docs/providers/tts/<id>.md
(URL, auth header, body/query fields, format mapping) and decodes a canned
response in that vendor's wire format. The catalog-wide tests then check that
every TTS catalog entry resolves, honours each declared format, and meters.
"""

import base64
import json

import httpx
import pytest

from speechrouter_gateway.audio.pcm_codec import wav_header
from speechrouter_gateway.config import Settings
from speechrouter_gateway.providers.aws import tts as polly
from speechrouter_gateway.providers.azure import tts as azure
from speechrouter_gateway.providers.base import ProviderStreamError
from speechrouter_gateway.providers.cartesia import tts as cartesia
from speechrouter_gateway.providers.deepgram import tts as deepgram
from speechrouter_gateway.providers.elevenlabs import tts as elevenlabs
from speechrouter_gateway.providers.fishaudio import tts as fishaudio
from speechrouter_gateway.providers.gemini import tts as gemini_tts
from speechrouter_gateway.providers.google import tts as google
from speechrouter_gateway.providers.groq import tts as groq
from speechrouter_gateway.providers.inworld import tts as inworld
from speechrouter_gateway.providers.minimax import tts as minimax
from speechrouter_gateway.providers.mistral import tts as mistral
from speechrouter_gateway.providers.murf import tts as murf
from speechrouter_gateway.providers.openai import tts as openai_tts
from speechrouter_gateway.providers.rime import tts as rime
from speechrouter_gateway.providers.smallest import tts as smallest
from speechrouter_gateway.providers.speechmatics import tts as speechmatics
from speechrouter_gateway.providers.together import tts as together
from speechrouter_gateway.providers.xai import tts as xai
from speechrouter_gateway.router.catalog import Catalog
from speechrouter_gateway.router.resolver import TTSRequest, resolve_tts
from speechrouter_gateway.tts.runner import TTSRun, tts_units

PCM = b"\x01\x00" * 2400  # 0.1 s at 24 kHz

SETTINGS = Settings(
    _env_file=None,
    openai_api_key="k-openai", gemini_api_key="k-gemini", elevenlabs_api_key="k-el",
    cartesia_api_key="k-car", deepgram_api_key="k-dg", azure_speech_key="k-az",
    azure_speech_region="eastus", google_tts_api_key="k-goog", rime_api_key="k-rime",
    inworld_api_key="k-inw", fishaudio_api_key="k-fish", minimax_api_key="k-mm",
    groq_api_key="k-groq", murf_api_key="k-murf", speechmatics_api_key="k-sm",
    xai_api_key="k-xai", aws_access_key_id="AKIDEXAMPLE",
    aws_secret_access_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", aws_region="us-east-1",
    mistral_api_key="k-mis", smallest_api_key="k-sma", together_api_key="k-tog",
)

MODULES = {"elevenlabs": elevenlabs, "cartesia": cartesia, "deepgram": deepgram,
           "azure": azure, "google": google, "rime": rime, "inworld": inworld,
           "fishaudio": fishaudio, "minimax": minimax, "groq": groq, "murf": murf,
           "speechmatics": speechmatics, "openai": openai_tts, "gemini": gemini_tts,
           "xai": xai, "aws": polly, "mistral": mistral, "smallest": smallest,
           "together": together}


def _f32(pcm: bytes) -> bytes:
    import array

    ints = array.array("h")
    ints.frombytes(pcm)
    return array.array("f", (i / 32767 for i in ints)).tobytes()


def _sse(*events: dict) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


def respond(provider: str, request: httpx.Request, pcm: bytes = PCM) -> httpx.Response:
    """A well-formed success response in each vendor's wire format."""
    if provider == "google":
        return httpx.Response(200, json={
            "audioContent": base64.b64encode(wav_header(24000) + pcm).decode()})
    if provider == "inworld":
        lines = [{"result": {"audioContent": base64.b64encode(pcm[:2400]).decode(),
                             "usage": {"processedCharactersCount": 11}}},
                 {"result": {"audioContent": base64.b64encode(pcm[2400:]).decode()}}]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
    if provider == "minimax":
        return httpx.Response(200, content=_sse(
            {"data": {"audio": pcm[:2400].hex(), "status": 1}, "base_resp": {"status_code": 0}},
            {"data": {"audio": pcm[2400:].hex(), "status": 1}, "base_resp": {"status_code": 0}},
            {"data": {"audio": pcm.hex(), "status": 2}, "extra_info": {"usage_characters": 11},
             "base_resp": {"status_code": 0, "status_msg": "success"}}))
    if provider in ("groq", "together"):
        return httpx.Response(200, content=wav_header(24000) + pcm)
    if provider == "mistral":
        f32 = _f32(pcm)
        return httpx.Response(200, content=_sse(
            {"type": "speech.audio.delta", "audio_data": base64.b64encode(f32[:4002]).decode()},
            {"type": "speech.audio.delta", "audio_data": base64.b64encode(f32[4002:]).decode()},
            {"type": "speech.audio.done"}))
    if provider == "aws":
        return httpx.Response(200, content=pcm, headers={"x-amzn-RequestCharacters": "11"})
    if provider == "openai":
        body = json.loads(request.content)
        if body.get("stream_format") == "sse":
            return httpx.Response(200, content=_sse(
                {"type": "speech.audio.delta", "audio": base64.b64encode(pcm).decode()},
                {"type": "speech.audio.done", "usage": {"input_tokens": 3, "output_tokens": 9}}))
        return httpx.Response(200, content=pcm)
    if provider == "gemini":
        return httpx.Response(200, content=_sse({
            "candidates": [{"content": {"parts": [{"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000",
                "data": base64.b64encode(pcm).decode()}}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2}}))
    return httpx.Response(200, content=pcm)


@pytest.fixture()
def capture(monkeypatch):
    """Route every adapter to a MockTransport that records requests."""
    seen: list[tuple[str, httpx.Request]] = []

    for provider, module in MODULES.items():
        def handler(request, provider=provider):
            seen.append((provider, request))
            return respond(provider, request)
        monkeypatch.setattr(module, "TRANSPORT", httpx.MockTransport(handler))
    return seen


async def synth(slug: str, text: str = "Hello world", **request_kw):
    resolved = resolve_tts(slug, TTSRequest(text_length=len(text), **request_kw), SETTINGS,
                           Catalog.load())
    adapter = resolved.build()
    run = TTSRun(resolved)
    audio = b""
    try:
        async for chunk in run.stream(adapter, text):
            audio += chunk
    finally:
        await adapter.close()
    return resolved, run, audio


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ------------------------------------------------------------- per provider


async def test_elevenlabs_request_contract(capture):
    resolved, run, audio = await synth("elevenlabs/eleven_flash_v2_5", format="pcm",
                                       sample_rate=16000, speed=1.1)
    (_, req), = capture
    assert req.url.path == "/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb/stream"
    assert req.url.params["output_format"] == "pcm_16000" and not resolved.wrap
    assert req.headers["xi-api-key"] == "k-el"
    assert body(req) == {"text": "Hello world", "model_id": "eleven_flash_v2_5",
                         "voice_settings": {"speed": 1.1}}
    assert audio == PCM and tts_units(resolved.entry, run.usage) == {"characters": 11}


async def test_elevenlabs_native_ulaw_and_wrapped_ulaw16k(capture):
    resolved, _, _ = await synth("elevenlabs/eleven_v3", format="mulaw")
    assert capture[0][1].url.params["output_format"] == "ulaw_8000" and not resolved.wrap
    resolved, _, _ = await synth("elevenlabs/eleven_v3", format="mulaw", sample_rate=16000)
    assert resolved.wrap and capture[1][1].url.params["output_format"].startswith("pcm_")


async def test_cartesia_request_contract(capture):
    resolved, _, audio = await synth("cartesia/sonic-3.6", format="alaw", language="en")
    (_, req), = capture
    assert str(req.url) == "https://api.cartesia.ai/tts/bytes"
    assert req.headers["authorization"] == "Bearer k-car"
    assert req.headers["cartesia-version"] == cartesia.API_VERSION
    assert body(req) == {
        "model_id": "sonic-3.6", "transcript": "Hello world",
        "voice": {"mode": "id", "id": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"},
        "output_format": {"container": "raw", "encoding": "pcm_alaw", "sample_rate": 8000},
        "language": "en"}
    assert not resolved.wrap and audio == PCM


async def test_deepgram_voice_is_model_and_char_count_header_wins(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=PCM, headers={"dg-char-count": "42"})
    monkeypatch.setattr(deepgram, "TRANSPORT", httpx.MockTransport(handler))
    resolved, run, _ = await synth("deepgram/aura-2", voice="aura-2-apollo-en", format="pcm")
    assert run.usage.characters == 42  # Deepgram's billed count, not len(text)
    assert tts_units(resolved.entry, run.usage) == {"characters": 42}


async def test_deepgram_query_params(capture):
    await synth("deepgram/aura-2", format="mulaw")
    (_, req), = capture
    assert req.url.path == "/v1/speak" and req.headers["authorization"] == "Token k-dg"
    assert dict(req.url.params) == {"model": "aura-2-thalia-en", "encoding": "mulaw",
                                    "container": "none", "sample_rate": "8000"}
    assert body(req) == {"text": "Hello world"}


async def test_azure_ssml_escapes_and_output_format(capture):
    resolved, _, audio = await synth("azure/neural", "Tom & <Jerry>", speed=1.2)
    assert resolved.out_format == "mp3"
    (_, req), = capture
    assert str(req.url) == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    assert req.headers["ocp-apim-subscription-key"] == "k-az"
    assert req.headers["x-microsoft-outputformat"] == "audio-24khz-48kbitrate-mono-mp3"
    ssml = req.content.decode()
    assert '<voice name="en-US-JennyNeural">' in ssml and 'xml:lang="en-US"' in ssml
    assert "Tom &amp; &lt;Jerry&gt;" in ssml and '<prosody rate="1.20">' in ssml


async def test_azure_pcm_rates(capture):
    await synth("azure/neural-hd", format="pcm", sample_rate=16000)
    assert capture[0][1].headers["x-microsoft-outputformat"] == "raw-16khz-16bit-mono-pcm"


async def test_google_decodes_base64_and_strips_wav_header(capture):
    resolved, run, audio = await synth("google/chirp3-hd", format="pcm")
    (_, req), = capture
    assert req.url.path == "/v1/text:synthesize" and req.headers["x-goog-api-key"] == "k-goog"
    assert "key=" not in str(req.url)
    assert body(req)["voice"] == {"languageCode": "en-US", "name": "en-US-Chirp3-HD-Kore"}
    assert body(req)["audioConfig"] == {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}
    assert audio == PCM and run.audio_seconds == 0.1


async def test_rime_accept_header_selects_format(capture):
    await synth("rime/coda", format="mulaw", speed=2.0)
    (_, req), = capture
    assert req.headers["accept"] == "audio/PCMU"
    assert body(req) == {"speaker": "astra", "text": "Hello world", "modelId": "coda",
                         "samplingRate": 8000, "timeScaleFactor": 0.5}


async def test_inworld_ndjson_audio_and_usage(capture):
    resolved, run, audio = await synth("inworld/inworld-tts-2", format="pcm")
    (_, req), = capture
    assert req.url.path == "/tts/v1/voice:stream" and req.headers["authorization"] == "Basic k-inw"
    assert body(req)["audioConfig"] == {"audioEncoding": "PCM", "sampleRateHertz": 24000}
    assert audio == PCM and run.usage.characters == 11


async def test_inworld_in_band_error_after_200(monkeypatch):
    lines = [json.dumps({"result": {"audioContent": base64.b64encode(PCM).decode()}}),
             json.dumps({"error": {"code": 3, "message": "bad voice"}})]
    monkeypatch.setattr(inworld, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(200, content="\n".join(lines).encode())))
    with pytest.raises(ProviderStreamError, match="bad voice"):
        await synth("inworld/inworld-tts-2", format="pcm")


async def test_fishaudio_model_header_and_utf8_byte_billing(capture):
    resolved, run, _ = await synth("fishaudio/s2.1-pro", "héllo 世界", format="pcm")
    (_, req), = capture
    assert req.headers["model"] == "s2.1-pro" and req.headers["authorization"] == "Bearer k-fish"
    assert body(req)["reference_id"] == fishaudio.CAPABILITIES.default_voice
    units = tts_units(resolved.entry, run.usage)
    assert units == {"utf8_bytes": len("héllo 世界".encode())}  # 13 bytes, 8 chars
    assert "characters" not in units


async def test_minimax_hex_sse_skips_repeated_final_audio(capture):
    resolved, run, audio = await synth("minimax/speech-2.8-turbo", format="pcm")
    (_, req), = capture
    assert req.url.path == "/v1/t2a_v2" and body(req)["stream"] is True
    assert body(req)["audio_setting"] == {"format": "pcm", "channel": 1, "sample_rate": 24000}
    assert audio == PCM  # not PCM + PCM again from the status:2 summary
    assert run.usage.characters == 11


async def test_minimax_in_band_error(monkeypatch):
    monkeypatch.setattr(minimax, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(
        200, content=_sse({"base_resp": {"status_code": 1008,
                                         "status_msg": "insufficient balance"}}))))
    with pytest.raises(ProviderStreamError) as info:
        await synth("minimax/speech-2.8-hd", format="pcm")
    assert info.value.code == "minimax_1008"


async def test_groq_requests_wav_and_yields_pcm(capture):
    resolved, _, audio = await synth("groq/orpheus-v1-english", format="pcm")
    (_, req), = capture
    assert req.url.path == "/openai/v1/audio/speech"
    assert body(req) == {"model": "canopylabs/orpheus-v1-english", "input": "Hello world",
                         "voice": "autumn", "response_format": "wav", "sample_rate": 24000}
    assert audio == PCM


async def test_groq_rejects_input_over_200_chars():
    from speechrouter_gateway.router.resolver import ResolveError

    with pytest.raises(ResolveError):
        resolve_tts("groq/orpheus-v1-english", TTSRequest(text_length=201), SETTINGS,
                    Catalog.load())


async def test_murf_request_contract(capture):
    await synth("murf/falcon-2", format="pcm", speed=1.2)
    (_, req), = capture
    assert req.headers["api-key"] == "k-murf"
    assert body(req) == {"text": "Hello world", "voiceId": "Natalie", "model": "falcon-2",
                         "format": "PCM", "sampleRate": 24000, "rate": 20}


async def test_speechmatics_16k_and_decimated_8k(capture):
    resolved, _, _ = await synth("speechmatics/preview", format="pcm")
    assert resolved.native_rate == 16000 and not resolved.wrap
    (_, req), = capture
    assert req.url.path == "/generate/megan" and req.url.params["output_format"] == "pcm_16000"
    resolved, _, audio = await synth("speechmatics/preview", format="mulaw")
    assert resolved.wrap and resolved.out_sample_rate == 8000
    assert len(audio) == len(PCM) // 2 // 2  # 16k s16 -> 8k G.711


# ------------------------------------------------------------- catalog-wide


def _tts_entries():
    return [e for e in Catalog.load().all() if e["kind"] == "tts"]


@pytest.mark.parametrize("slug", [e["slug"] for e in _tts_entries()])
async def test_every_catalog_model_synthesizes_and_meters(capture, slug):
    resolved, run, audio = await synth(slug)
    assert audio, slug
    units = tts_units(resolved.entry, run.usage)
    assert units, f"{slug}: produced audio but no priced units"
    pricing = resolved.entry["pricing"]
    from speechrouter_gateway.router.catalog import UNIT_RATE_FIELDS
    priced = {UNIT_RATE_FIELDS[k][0] for k in units}
    assert priced & set(pricing), f"{slug}: units {units} hit no rate in {pricing}"


@pytest.mark.parametrize("slug,fmt", [(e["slug"], f) for e in _tts_entries()
                                      for f in e["capabilities"]["formats"]])
def test_every_declared_format_resolves(slug, fmt):
    resolved = resolve_tts(slug, TTSRequest(format=fmt), SETTINGS, Catalog.load())
    assert resolved.out_format == fmt
    assert resolved.config.format in MODULES[slug.split("/")[0]].CAPABILITIES.formats


def test_tts_entries_carry_pricing_provenance():
    for entry in _tts_entries():
        if entry["provider"] in {"openai", "gemini"}:
            continue  # phase 1 entries: sources in docs/providers/*.md
        assert entry["pricing_source"] and entry["pricing_checked"] == "2026-10-13", entry["slug"]


async def test_failed_request_bills_nothing_even_with_precounted_bytes(monkeypatch):
    monkeypatch.setattr(fishaudio, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(402, json={"status": 402, "message": "no credit"})))
    resolved = resolve_tts("fishaudio/s2.1-pro", TTSRequest(), SETTINGS, Catalog.load())
    run = TTSRun(resolved)
    adapter = resolved.build()
    with pytest.raises(ProviderStreamError):
        async for _ in run.stream(adapter, "hello"):
            pass
    assert tts_units(resolved.entry, run.usage, produced=run.produced_bytes > 0) == {}


def test_tts_base_url_override_routes_to_mock():
    from speechrouter_gateway.config import tts_base_url

    cfg = SETTINGS.model_copy(update={"tts_base_urls": '{"rime": "http://127.0.0.1:9/"}'})
    assert tts_base_url(cfg, "rime", rime.BASE) == "http://127.0.0.1:9"
    assert tts_base_url(cfg, "murf", murf.BASE) == murf.BASE
    assert tts_base_url(SETTINGS.model_copy(update={"tts_base_urls": "not json"}), "rime",
                        rime.BASE) == rime.BASE


async def test_minimax_concurrent_streams_on_one_adapter_stay_independent(monkeypatch):
    """/v1/speak prefetch runs two synthesize() calls on one adapter."""
    import asyncio

    monkeypatch.setattr(minimax, "TRANSPORT", httpx.MockTransport(
        lambda r: respond("minimax", r)))
    resolved = resolve_tts("minimax/speech-2.8-turbo", TTSRequest(format="pcm"), SETTINGS,
                           Catalog.load())
    adapter = resolved.build()

    async def one(text):
        run = TTSRun(resolved)
        return b"".join([c async for c in run.stream(adapter, text)])

    first, second = await asyncio.gather(one("first segment"), one("second segment"))
    await adapter.close()
    assert first == PCM and second == PCM


# ------------------------------------------------------------- phase 3


async def test_polly_sigv4_body_and_billed_chars(capture):
    resolved, run, audio = await synth("aws/polly-neural", "Hi & bye", format="mulaw", speed=1.25)
    (_, req), = capture
    assert str(req.url) == "https://polly.us-east-1.amazonaws.com/v1/speech"
    auth = req.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/us-east-1/polly/aws4_request" in auth
    assert "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date" in auth
    assert body(req) == {"Engine": "neural", "OutputFormat": "mulaw", "SampleRate": "8000",
                         "Text": '<speak><prosody rate="125%">Hi &amp; bye</prosody></speak>',
                         "TextType": "ssml", "VoiceId": "Joanna"}
    assert run.usage.characters == 11  # x-amzn-RequestCharacters wins
    assert not resolved.wrap


def test_polly_signature_matches_aws_documentation_vector():
    """AWS's published SigV4 example (IAM ListUsers, 2015-08-30)."""
    import datetime

    from speechrouter_gateway.providers.aws.signer import sign_headers

    headers = sign_headers(
        method="GET", url="https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, body=b"",
        access_key="AKIDEXAMPLE", secret_key="wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        region="us-east-1", service="iam", content_sha256_header=False,
        now=datetime.datetime(2015, 8, 30, 12, 36, tzinfo=datetime.UTC))
    assert headers["Authorization"].endswith(
        "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7")


async def test_polly_pcm_is_16k_native_and_24k_rejected(capture):
    from speechrouter_gateway.router.resolver import ResolveError

    resolved, _, _ = await synth("aws/polly-generative", format="pcm")
    assert resolved.native_rate == 16000 and body(capture[0][1])["SampleRate"] == "16000"
    with pytest.raises(ResolveError):
        resolve_tts("aws/polly-generative", TTSRequest(format="pcm", sample_rate=24000),
                    SETTINGS, Catalog.load())


async def test_mistral_float32_pcm_becomes_s16(capture):
    resolved, _, audio = await synth("mistral/voxtral-mini-tts-2603", format="pcm")
    (_, req), = capture
    assert body(req) == {"model": "voxtral-mini-tts-2603", "input": "Hello world",
                         "voice_id": "fr_marie_neutral", "response_format": "pcm",
                         "stream": True}
    import array

    got, want = array.array("h"), array.array("h")
    got.frombytes(audio)
    want.frombytes(PCM)
    assert len(got) == len(want) and max(abs(a - b) for a, b in zip(got, want, strict=True)) <= 1


async def test_smallest_request_contract(capture):
    resolved, _, _ = await synth("smallest/lightning_v3.1", format="mulaw", speed=1.5)
    (_, req), = capture
    assert str(req.url) == "https://api.smallest.ai/waves/v1/tts"
    assert body(req) == {"text": "Hello world", "voice_id": "liam", "model": "lightning_v3.1",
                         "sample_rate": 8000, "output_format": "ulaw", "speed": 1.5}
    assert not resolved.wrap


async def test_together_kokoro_wav_stripped_and_8k_decimated(capture):
    resolved, _, audio = await synth("together/kokoro-82m", format="mulaw")
    (_, req), = capture
    assert str(req.url) == "https://api.together.ai/v1/audio/speech"
    assert body(req) == {"model": "hexgrad/Kokoro-82M", "input": "Hello world",
                         "voice": "af_heart", "response_format": "wav",
                         "response_encoding": "pcm_s16le", "sample_rate": 24000}
    assert resolved.wrap and len(audio) == len(PCM) // 2 // 3  # 24k s16 -> 8k G.711


async def test_xai_rest_contract(capture):
    await synth("xai/grok-tts", format="mulaw", language="en")
    (_, req), = capture
    assert req.url.path == "/v1/tts" and req.headers["authorization"] == "Bearer k-xai"
    assert body(req) == {"text": "Hello world", "voice_id": "eve", "language": "en",
                         "output_format": {"codec": "mulaw", "sample_rate": 8000}}


async def test_deepgram_flux_rest_uses_v2_without_container(capture):
    await synth("deepgram/flux", format="pcm")
    (_, req), = capture
    assert req.url.path == "/v2/speak"
    assert dict(req.url.params) == {"model": "flux-haley-en", "encoding": "linear16",
                                    "sample_rate": "24000"}


def test_native_stream_offered_only_where_it_fits():
    def adapter_for(slug, fmt):
        resolved = resolve_tts(slug, TTSRequest(format=fmt), SETTINGS, Catalog.load())
        return resolved.build().open_stream(resolved.config)

    assert adapter_for("xai/grok-tts", "pcm") is not None
    assert adapter_for("deepgram/flux", "mulaw") is not None
    assert adapter_for("deepgram/flux", "mp3") is None  # Flux socket is raw-only
    assert adapter_for("deepgram/aura-2", "pcm") is None
    assert adapter_for("aws/polly-neural", "pcm") is None


# ------------------------------------------------- native sockets (fake upstreams)


class FakeSocketServer:
    """In-loop websockets server running a scripted handler."""

    def __init__(self, handler):
        self._handler = handler
        self.requests: list = []

    async def __aenter__(self):
        import websockets

        async def wrapped(conn):
            self.requests.append((conn.request.path, dict(conn.request.headers)))
            await self._handler(conn)

        self._server = await websockets.serve(wrapped, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()


def _stream_for(slug, fmt, base, **kw):
    settings = SETTINGS.model_copy(update={
        "tts_base_urls": json.dumps({slug.split("/")[0]: base})})
    resolved = resolve_tts(slug, TTSRequest(format=fmt, **kw), settings, Catalog.load())
    return resolved, resolved.build().open_stream(resolved.config)


async def test_xai_native_stream_barge_in_drops_stale_audio():
    import asyncio

    received = []

    async def handler(conn):
        async for raw in conn:
            msg = json.loads(raw)
            received.append(msg)
            if msg["type"] == "text.delta":
                await conn.send(json.dumps({"type": "audio.delta",
                                            "delta": base64.b64encode(b"A" * 160).decode()}))
            elif msg["type"] == "text.clear":
                # audio already in flight before the ack is stale
                await conn.send(json.dumps({"type": "audio.delta",
                                            "delta": base64.b64encode(b"S" * 160).decode()}))
                await conn.send(json.dumps({"type": "audio.clear"}))
            elif msg["type"] == "text.done":
                await conn.send(json.dumps({"type": "audio.delta",
                                            "delta": base64.b64encode(b"B" * 160).decode()}))
                await conn.send(json.dumps({"type": "audio.done", "trace_id": "t1"}))

    async with FakeSocketServer(handler) as server:
        resolved, stream = _stream_for("xai/grok-tts", "mulaw", server.base, language="en")
        await stream.connect(resolved.config)
        chunks: list[bytes] = []
        reader = asyncio.create_task(_collect_stream(stream, chunks))
        await stream.send_text("Hello there.")
        await _until_len(chunks, 1)
        assert await stream.clear() == {}
        await stream.send_text("Fresh.")
        await stream.finish()
        await asyncio.wait_for(reader, 2)
        await stream.close()

    path, headers = server.requests[0]
    assert path.startswith("/v1/tts?") and "codec=mulaw" in path and "sample_rate=8000" in path
    assert "language=en" in path and "voice=eve" in path
    assert headers["authorization"] == "Bearer k-xai"
    assert [m["type"] for m in received] == ["text.delta", "text.clear", "text.delta",
                                             "text.done"]
    assert b"S" not in b"".join(chunks)  # stale pre-ack audio never surfaced
    assert stream.usage.characters == len("Hello there.") + len("Fresh.")


async def test_flux_native_stream_interrupt_reports_text_spoken():
    import asyncio

    received = []

    async def handler(conn):
        await conn.send(json.dumps({"type": "Connected", "request_id": "r1"}))
        async for raw in conn:
            msg = json.loads(raw)
            received.append(msg)
            if msg["type"] == "Speak":
                await conn.send(b"\x01\x00" * 240)  # 10 ms of 24 kHz linear16
            elif msg["type"] == "Interrupt":
                await conn.send(b"\x09\x00" * 240)  # stale
                await conn.send(json.dumps({"type": "SpeechInterrupted", "audio_played_ms": 10,
                                            "text_spoken": "Hello", "text_remaining": " there."}))
            elif msg["type"] == "Close":
                await conn.send(json.dumps({"type": "SessionMetadata",
                                            "total_billable_character_count": 9}))
                await conn.close()
                return

    async with FakeSocketServer(handler) as server:
        resolved, stream = _stream_for("deepgram/flux", "pcm", server.base)
        await stream.connect(resolved.config)
        chunks: list[bytes] = []
        reader = asyncio.create_task(_collect_stream(stream, chunks))
        await stream.send_text("Hello there.")
        await _until_len(chunks, 1)
        info = await stream.clear(playback_ms=7)
        await stream.finish()
        await asyncio.wait_for(reader, 2)
        await stream.close()

    path, headers = server.requests[0]
    assert path.startswith("/v2/speak?") and "model=flux-haley-en" in path
    assert "container" not in path and headers["authorization"] == "Token k-dg"
    assert info == {"text_spoken": "Hello", "text_remaining": " there."}
    interrupt = next(m for m in received if m["type"] == "Interrupt")
    assert interrupt["playback_offset"] == {"type": "time_ms", "value": 7}
    assert b"\x09\x00" not in b"".join(chunks)
    assert stream.usage.characters == 9  # SessionMetadata billable count wins


async def _collect_stream(stream, sink):
    async for chunk in stream.audio():
        sink.append(chunk)


async def _until_len(items, n, limit=2.0):
    import asyncio

    async with asyncio.timeout(limit):
        while len(items) < n:  # noqa: ASYNC110 - observing a black box
            await asyncio.sleep(0.005)


async def test_native_speak_session_relays_cleared_with_text_spoken():
    """End to end through NativeSpeakSession with a scripted TTSStream."""
    import asyncio

    from speechrouter_gateway.providers.base import TTSStream, TTSUsage
    from speechrouter_gateway.tts.native_session import NativeSpeakSession

    class ScriptedStream(TTSStream):
        def __init__(self):
            self.usage = TTSUsage()
            self.queue: asyncio.Queue = asyncio.Queue()

        async def connect(self, config):
            pass

        async def send_text(self, text):
            self.usage.characters += len(text)
            await self.queue.put(b"\x01\x00" * 240)

        async def clear(self, playback_ms=None):
            return {"text_spoken": "Hi", "text_remaining": " you", "ignored": 1}

        async def finish(self):
            await self.queue.put(None)

        async def audio(self):
            while (chunk := await self.queue.get()) is not None:
                yield chunk

        async def close(self):
            pass

    class Transport:
        def __init__(self):
            self.inbox: asyncio.Queue = asyncio.Queue()
            self.sent: list = []

        async def recv(self):
            return await self.inbox.get()

        async def send_event(self, event):
            self.sent.append(json.loads(event.model_dump_json(exclude_none=True)))

        async def send_audio(self, data):
            self.sent.append(data)

    class Emitter:
        events: list = []

        async def emit(self, event):
            self.events.append(event)

    transport = Transport()
    resolved = resolve_tts("xai/grok-tts", TTSRequest(format="pcm"), SETTINGS, Catalog.load())
    session = NativeSpeakSession(transport, resolved, ScriptedStream(), Emitter(), "k1",
                                 SETTINGS)
    task = asyncio.create_task(session.run())
    for event in ({"type": "text.delta", "text": "Hi you"}, {"type": "clear"},
                  {"type": "text.delta", "text": "Again"}, {"type": "finalize"}):
        await transport.inbox.put(json.dumps(event))
    await asyncio.wait_for(task, 3)
    events = [e for e in transport.sent if isinstance(e, dict)]
    cleared = next(e for e in events if e["type"] == "cleared")
    assert cleared == {"type": "cleared", "last_seq": cleared["last_seq"], "text_spoken": "Hi",
                       "text_remaining": " you"}
    assert events[0]["type"] == "session.open" and events[-1]["type"] == "done"
    (usage,) = Emitter.events
    assert usage.kind == "tts_stream" and usage.characters == len("Hi you") + len("Again")
    assert usage.units == {"characters": 11.0} and usage.list_cost_usd > 0


# ------------------------------------------------- live-verified fixtures (2026-10-13)


async def test_mistral_real_sse_shape(monkeypatch):
    """Shape captured from the real API: event: speech.audio.delta {type,
    audio_data}, then speech.audio.done {type, usage{...}}."""
    f32 = _f32(PCM)
    stream = (
        "event: speech.audio.delta\n"
        f"data: {json.dumps({'type': 'speech.audio.delta', 'audio_data': base64.b64encode(f32).decode()})}\n\n"  # noqa: E501
        "event: speech.audio.done\n"
        'data: {"type": "speech.audio.done", "usage": {"prompt_tokens": 121, '
        '"completion_tokens": 23040, "total_tokens": 23161}}\n\n'
    ).encode()
    monkeypatch.setattr(mistral, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(200, content=stream,
                                 headers={"content-type": "text/event-stream"})))
    _, run, audio = await synth("mistral/voxtral-mini-tts-2603", format="pcm")
    assert len(audio) == len(PCM)
    assert tts_units(Catalog.load().find("mistral/voxtral-mini-tts-2603"), run.usage) == {
        "characters": 11}


async def test_azure_empty_400_explains_region_voice(monkeypatch):
    monkeypatch.setattr(azure, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(400, content=b"")))  # verified: westus + Dragon HD
    with pytest.raises(ProviderStreamError) as info:
        await synth("azure/neural-hd", format="pcm")
    assert "not available on this Azure Speech resource's region" in str(info.value)
    assert info.value.code == "invalid_request"


async def test_groq_terms_acceptance_400_is_account_error_not_user_error(monkeypatch):
    body = {"error": {"message": "The model `canopylabs/orpheus-v1-english` requires terms "
                                 "acceptance. Please have the org admin accept the terms at "
                                 "https://console.groq.com/playground?model=x",
                      "type": "invalid_request_error", "code": "model_terms_required"}}
    monkeypatch.setattr(groq, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(400, json=body)))
    with pytest.raises(ProviderStreamError) as info:
        await synth("groq/orpheus-v1-english", format="pcm")
    assert info.value.code == "account" and not info.value.recoverable


def test_openai_tts_estimate_uses_measured_rate():
    from speechrouter_gateway.providers.base import TTSConfig, TTSUsage

    usage = TTSUsage()
    openai_tts.OpenAITTS("k", "https://x/v1").estimate_usage(
        "x" * 40, TTSConfig(model="gpt-4o-mini-tts", voice="alloy", format="pcm"), 3.4, usage)
    assert usage.tokens["audio_output_tokens"] == 92  # ceil(3.4 * 26.8); real: 91
