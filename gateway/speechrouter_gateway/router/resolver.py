"""Slug resolution: "deepgram/nova-3" + requested features -> validated attempt.

Rejects impossible requests (unknown model, unsupported capability, missing
credentials) BEFORE any provider connection is opened."""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from ..config import Settings
from ..protocol.events import Code
from ..providers.base import STTConfig, STTStreamProvider
from ..providers.registry import ProviderNotConfigured, stt_stream_provider
from .catalog import Catalog


class ResolveError(Exception):
    def __init__(self, code: Code, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StreamRequest:
    encoding: str = "linear16"
    sample_rate: int = 16000
    channels: int = 1
    language: str | None = None
    interim_results: bool = True
    diarization: bool = False
    keyterms: tuple[str, ...] = ()
    provider_params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedAttempt:
    slug: str
    config: STTConfig
    build: Callable[[], STTStreamProvider]


def resolve_stream(
    slug: str, request: StreamRequest, settings: Settings, catalog: Catalog
) -> ResolvedAttempt:
    provider_id, _, model_name = slug.partition("/")
    if not provider_id or not model_name:
        raise ResolveError(Code.model_not_found, f"invalid model slug '{slug}'")

    registered = stt_stream_provider(provider_id)
    if registered is None:
        raise ResolveError(Code.model_not_found, f"unknown provider '{provider_id}'")
    if catalog.find(slug) is None:
        raise ResolveError(Code.model_not_found, f"unknown model '{slug}'")

    caps = registered.capabilities
    if request.diarization and not caps.diarization:
        raise ResolveError(Code.unsupported_capability, f"'{slug}' does not support diarization")
    if caps.encodings and request.encoding not in caps.encodings:
        raise ResolveError(
            Code.unsupported_encoding, f"'{slug}' does not accept encoding '{request.encoding}'"
        )

    # Fail on missing credentials now, not mid-connect. Builders are cheap
    # constructors by contract; the probe instance is discarded.
    try:
        _ = registered.build(settings)
    except ProviderNotConfigured as exc:
        raise ResolveError(Code.invalid_request, str(exc)) from exc

    config = STTConfig(
        model=model_name,
        encoding=request.encoding,
        sample_rate=request.sample_rate,
        channels=request.channels,
        language=request.language,
        interim_results=request.interim_results,
        diarization=request.diarization,
        keyterms=request.keyterms,
        provider_params=request.provider_params,
    )
    return ResolvedAttempt(slug=slug, config=config, build=partial(registered.build, settings))
