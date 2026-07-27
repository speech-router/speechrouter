"""Groq batch STT — OpenAI-compatible endpoint, whisper models.

Facts (docs/providers/groq.md): no provider srt/vtt (gateway synthesizes from
verbose_json words), distil-whisper-large-v3-en is retired (rejected at the
catalog layer by not listing it), 10-second minimum billing per request.
"""

from ...config import Settings
from ..base import Capabilities
from ..openai_compat import OpenAICompatBatch
from ..registry import ProviderNotConfigured, register_stt_batch

CAPABILITIES = Capabilities(
    batch=True,
    word_timestamps=True,
    languages=frozenset({"auto"}),
)


@register_stt_batch("groq", capabilities=CAPABILITIES)
def build(settings: Settings) -> "GroqSTTBatch":
    if not settings.groq_api_key:
        raise ProviderNotConfigured("groq")
    return GroqSTTBatch(settings.groq_api_key)


class GroqSTTBatch(OpenAICompatBatch):
    name = "groq"
    capabilities = CAPABILITIES
    base_url = "https://api.groq.com/openai/v1"
