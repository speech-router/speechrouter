"""Optional audio-persistence hook.

Off by default everywhere, including the hosted api.speechrouter.ai — the
gateway's core promise is that audio passes straight through to the provider
and nothing else ever sees it. A sink is how a self-hoster who genuinely
needs a copy (compliance, QA review, dispute resolution) opts in, without
that capability ever being silently active for anyone who didn't ask for it.

Chunks are handed to the sink as they arrive, same order as sent to the
provider. A sink must never raise into the session's hot audio path --
callers are expected to swallow/log sink errors, not propagate them.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..config import Settings


class AudioSink(Protocol):
    async def on_chunk(self, session_id: str, chunk: bytes) -> None:
        """One binary audio chunk, in send order."""
        ...

    async def on_session_end(self, session_id: str) -> None:
        """Session is over (any outcome) -- flush/finalize whatever is buffered."""
        ...


class NoOpAudioSink:
    """The default everywhere. Does nothing; costs nothing."""

    async def on_chunk(self, session_id: str, chunk: bytes) -> None:
        return

    async def on_session_end(self, session_id: str) -> None:
        return


def build_audio_sink(cfg: "Settings") -> "AudioSink":
    from ..config import AudioSinkKind  # noqa: PLC0415 - avoid import cycle

    match cfg.audio_sink:
        case AudioSinkKind.none:
            return NoOpAudioSink()
        case AudioSinkKind.s3:
            from .s3_sink import S3AudioSink  # noqa: PLC0415 - optional path

            return S3AudioSink(
                bucket=cfg.audio_sink_bucket,
                region=cfg.audio_sink_region or cfg.aws_region,
                access_key=cfg.audio_sink_access_key or cfg.aws_access_key_id,
                secret_key=cfg.audio_sink_secret_key or cfg.aws_secret_access_key,
                prefix=cfg.audio_sink_prefix,
            )
