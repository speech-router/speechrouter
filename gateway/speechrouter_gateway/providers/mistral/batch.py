"""Mistral (Voxtral) batch STT — OpenAI-style endpoint with extras.

Extras (docs/providers/mistral.md): diarize=true, context_bias keyword
boosting, timestamp_granularities, up to 3 hours of audio per request.
"""

from ...config import Settings
from ..base import Capabilities, STTConfig
from ..openai_compat import OpenAICompatBatch
from ..registry import ProviderNotConfigured, register_stt_batch

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,
    diarization=True,
    keyterms=True,
    keyterms_max=100,
    languages=frozenset({"auto"}),
)


@register_stt_batch("mistral", capabilities=CAPABILITIES)
def build(settings: Settings) -> "MistralSTTBatch":
    if not settings.mistral_api_key:
        raise ProviderNotConfigured("mistral")
    return MistralSTTBatch(settings.mistral_api_key)


class MistralSTTBatch(OpenAICompatBatch):
    name = "mistral"
    capabilities = CAPABILITIES
    base_url = "https://api.mistral.ai/v1"

    def extra_form(self, config: STTConfig) -> dict[str, str]:
        extra: dict[str, str] = {}
        if config.diarization:
            extra["diarize"] = "true"
        if config.keyterms:
            # repeated form field; httpx data dict can't repeat -> comma join
            # is NOT documented, so send the first 100 as a single field list
            extra["context_bias"] = ",".join(config.keyterms[:100])
        return extra

    def wants_verbose(self, config: STTConfig) -> bool:
        # Mistral uses timestamp_granularities without verbose_json naming;
        # the OpenAI-style verbose request works but verify on live pass.
        return True
