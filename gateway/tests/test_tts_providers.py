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
from speechrouter_gateway.providers.murf import tts as murf
from speechrouter_gateway.providers.openai import tts as openai_tts
from speechrouter_gateway.providers.rime import tts as rime
from speechrouter_gateway.providers.speechmatics import tts as speechmatics
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
)

MODULES = {"elevenlabs": elevenlabs, "cartesia": cartesia, "deepgram": deepgram,
           "azure": azure, "google": google, "rime": rime, "inworld": inworld,
           "fishaudio": fishaudio, "minimax": minimax, "groq": groq, "murf": murf,
           "speechmatics": speechmatics, "openai": openai_tts, "gemini": gemini_tts}


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
    if provider == "groq":
        return httpx.Response(200, content=wav_header(24000) + pcm)
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
