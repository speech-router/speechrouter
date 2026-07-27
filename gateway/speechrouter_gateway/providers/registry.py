"""Adapter registry: provider id -> adapter factory. Adapters self-register."""

from collections.abc import Callable

from .base import STTBatchProvider, STTStreamProvider

_stt_stream: dict[str, Callable[..., STTStreamProvider]] = {}
_stt_batch: dict[str, Callable[..., STTBatchProvider]] = {}


def register_stt_stream(provider_id: str):
    def deco(factory: Callable[..., STTStreamProvider]):
        _stt_stream[provider_id] = factory
        return factory

    return deco


def register_stt_batch(provider_id: str):
    def deco(factory: Callable[..., STTBatchProvider]):
        _stt_batch[provider_id] = factory
        return factory

    return deco


def stt_stream_factory(provider_id: str) -> Callable[..., STTStreamProvider] | None:
    return _stt_stream.get(provider_id)


def stt_batch_factory(provider_id: str) -> Callable[..., STTBatchProvider] | None:
    return _stt_batch.get(provider_id)
