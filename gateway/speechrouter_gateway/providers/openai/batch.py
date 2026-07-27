"""OpenAI batch STT.

Format matrix (docs/providers/openai.md): whisper-1 supports verbose_json
(word timestamps); gpt-4o-transcribe / gpt-4o-mini-transcribe are json-only —
no word timings, so srt/vtt from those models degrade to a single cue.
"""

from ...config import Settings
from ..base import Capabilities, STTConfig
from ..openai_compat import OpenAICompatBatch
from ..registry import ProviderNotConfigured, register_stt_batch

_VERBOSE_MODELS = {"whisper-1"}

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,  # whisper-1 only; per-model truth in models.json
    languages=frozenset({"auto"}),
)


@register_stt_batch("openai", capabilities=CAPABILITIES)
def build(settings: Settings) -> "OpenAISTTBatch":
    if not settings.openai_api_key:
        raise ProviderNotConfigured("openai")
    return OpenAISTTBatch(settings.openai_api_key)


class OpenAISTTBatch(OpenAICompatBatch):
    name = "openai"
    capabilities = CAPABILITIES
    base_url = "https://api.openai.com/v1"

    def wants_verbose(self, config: STTConfig) -> bool:
        return config.model in _VERBOSE_MODELS
