"""One synthesis call through an adapter, plus everything the gateway owes
around it: format wrapping, generated-duration accounting, priced units.

Shared by POST /v1/audio/speech (one run per request) and WSS /v1/speak
(one run per text segment, accumulated into the session's totals).
"""

from collections.abc import AsyncIterator

from ..audio.mp3_frames import Mp3DurationCounter
from ..audio.pcm_codec import PcmConverter
from ..providers.base import TTSProvider, TTSUsage
from ..router.catalog import UNIT_RATE_FIELDS, effective_pricing, price_units
from ..router.resolver import ResolvedTTS

_WAV_HEADER = 44


class TTSRun:
    def __init__(self, resolved: ResolvedTTS, usage: TTSUsage | None = None):
        self._resolved = resolved
        self.usage = usage or TTSUsage()
        self._pcm_bytes = 0  # adapter pcm (native rate) seen
        self._wav_bytes = 0
        self._mp3 = Mp3DurationCounter() if resolved.config.format == "mp3" else None
        self.produced_bytes = 0  # adapter output seen; 0 = provider generated nothing

    async def stream(self, adapter: TTSProvider, text: str) -> AsyncIterator[bytes]:
        resolved = self._resolved
        converter = (
            PcmConverter(resolved.out_format, resolved.native_rate, resolved.out_sample_rate)
            if resolved.wrap
            else None
        )
        native = resolved.config.format
        async for chunk in adapter.synthesize(text, resolved.config, self.usage):
            self.produced_bytes += len(chunk)
            if native == "pcm":
                self._pcm_bytes += len(chunk)
            elif native == "wav":
                self._wav_bytes += len(chunk)
            elif self._mp3 is not None:
                self._mp3.feed(chunk)
            out = converter.feed(chunk) if converter else chunk
            if out:
                yield out
        if converter is not None:
            tail = converter.flush()
            if tail:
                yield tail

    @property
    def audio_seconds(self) -> float:
        """Generated duration. Exact for pcm/wav/G.711 and mp3; 0 for
        opus/aac/flac, whose duration is not derivable without decoding."""
        rate = self._resolved.native_rate
        if self._pcm_bytes:
            return self._pcm_bytes / (2 * rate)
        if self._wav_bytes:
            return max(0, self._wav_bytes - _WAV_HEADER) / (2 * rate)
        if self._mp3 is not None:
            return self._mp3.seconds
        return self.usage.audio_seconds


def tts_units(entry: dict, usage: TTSUsage, produced: bool = True) -> dict[str, float]:
    """Priced quantities per PLAN §3.0: provider-reported tokens, plus
    characters when the model is priced per character. A request the
    provider failed before generating anything costs nothing upstream, so
    it carries no characters (reported tokens, if any, still count)."""
    if not produced and not usage.tokens:
        return {}
    units = {k: v for k, v in usage.tokens.items() if k in UNIT_RATE_FIELDS and v}
    if "per_character_usd" in effective_pricing(entry) and usage.characters:
        units["characters"] = float(usage.characters)
    return units


def list_cost(entry: dict, units: dict[str, float], byok: bool) -> float:
    return 0.0 if byok else round(price_units(entry, units), 8)
