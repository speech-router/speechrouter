"""Amazon Polly TTS: SynthesizeSpeech REST (docs/providers/tts/polly.md).

- POST https://polly.{region}.amazonaws.com/v1/speech, SigV4 (service
  "polly") via providers/aws/signer.sign_headers — no boto3, no AWS SDK.
- PascalCase JSON body {Engine, OutputFormat, SampleRate (string), Text,
  TextType, VoiceId, LanguageCode?}; raw audio streams back; billed count in
  `x-amzn-RequestCharacters`.
- Engines are the catalog models: aws/polly-standard | -neural | -long-form |
  -generative. pcm is 8 or 16 kHz only; mulaw/alaw 8 kHz; mp3 at 24 kHz.
- Speed has no field: it rides SSML <prosody rate>.
- StartSpeechSynthesisStream (generative bidi, HTTP/2 event stream) is not
  used yet: /v1/speak segments over SynthesizeSpeech.
"""

import json
from xml.sax.saxutils import escape

import httpx

from ...config import Settings, tts_base_url
from ..base import TTSCapabilities, TTSProvider
from ..http_tts import HTTPStreamTTS
from ..registry import ProviderNotConfigured, register_tts
from .signer import sign_headers

CAPABILITIES = TTSCapabilities(
    default_voice="Joanna",
    formats=frozenset({"pcm", "mp3", "opus", "mulaw", "alaw"}),
    sample_rates=frozenset({8000, 16000}),
    format_rates={"mulaw": frozenset({8000}), "alaw": frozenset({8000})},
    max_input_chars=3000,
    speed=True,
)

_ENGINE = {"polly-standard": "standard", "polly-neural": "neural",
           "polly-long-form": "long-form", "polly-generative": "generative"}
_FORMAT = {"pcm": "pcm", "mp3": "mp3", "opus": "ogg_opus", "mulaw": "mulaw", "alaw": "alaw"}

TRANSPORT: httpx.AsyncBaseTransport | None = None


@register_tts("aws", capabilities=CAPABILITIES)
def build(settings: Settings) -> "PollyTTS":
    if not (settings.aws_access_key_id and settings.aws_secret_access_key):
        raise ProviderNotConfigured("aws")
    region = settings.aws_region or "us-east-1"
    return PollyTTS({
        "access_key": settings.aws_access_key_id, "secret_key": settings.aws_secret_access_key,
        "region": region,
        "base": tts_base_url(settings, "aws", f"https://polly.{region}.amazonaws.com"),
    }, TRANSPORT)


def build_body(text: str, config) -> dict:  # noqa: ANN001
    rate = {"mp3": "24000", "opus": "48000"}.get(config.format, str(config.sample_rate))
    body: dict = {"Engine": _ENGINE[config.model], "OutputFormat": _FORMAT[config.format],
                  "SampleRate": rate, "Text": text, "TextType": "text",
                  "VoiceId": config.voice}
    if config.speed is not None:
        body["Text"] = (f'<speak><prosody rate="{round(config.speed * 100)}%">'
                        f"{escape(text)}</prosody></speak>")
        body["TextType"] = "ssml"
    if config.language:
        body["LanguageCode"] = config.language
    for key, value in config.provider_params.items():
        body.setdefault(key, value)
    return body


class PollyTTS(HTTPStreamTTS, TTSProvider):
    name = "aws"
    capabilities = CAPABILITIES

    def build_request(self, text, config):
        url = f"{self.credentials['base']}/v1/speech"
        payload = json.dumps(build_body(text, config)).encode()
        headers = sign_headers(
            method="POST", url=url, headers={"Content-Type": "application/json"},
            body=payload, access_key=self.credentials["access_key"],
            secret_key=self.credentials["secret_key"], region=self.credentials["region"],
            service="polly")
        return {"url": url, "headers": headers, "content": payload}

    def on_headers(self, headers, usage):
        count = headers.get("x-amzn-RequestCharacters")
        if count and count.isdigit():
            usage.characters = int(count)
