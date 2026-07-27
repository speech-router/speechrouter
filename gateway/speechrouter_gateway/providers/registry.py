"""Adapter registry: provider id -> (builder, capabilities). Adapters self-register.

Builders take Settings and return a fresh adapter instance (one instance per
upstream session). A builder raises ProviderNotConfigured when the gateway
lacks credentials for its provider — resolved at request time, not boot, so a
self-host with only a Deepgram key still serves deepgram/* models.
"""

from collections.abc import Callable
from typing import NamedTuple

from ..config import Settings
from .base import Capabilities, STTBatchProvider, STTStreamProvider


class ProviderNotConfigured(Exception):
    def __init__(self, provider_id: str):
        super().__init__(f"provider '{provider_id}' has no credentials configured")
        self.provider_id = provider_id


class RegisteredStream(NamedTuple):
    build: Callable[[Settings], STTStreamProvider]
    capabilities: Capabilities


class RegisteredBatch(NamedTuple):
    build: Callable[[Settings], STTBatchProvider]
    capabilities: Capabilities


_stt_stream: dict[str, RegisteredStream] = {}
_stt_batch: dict[str, RegisteredBatch] = {}


def register_stt_stream(provider_id: str, *, capabilities: Capabilities):
    def deco(build: Callable[[Settings], STTStreamProvider]):
        _stt_stream[provider_id] = RegisteredStream(build, capabilities)
        return build

    return deco


def register_stt_batch(provider_id: str, *, capabilities: Capabilities):
    def deco(build: Callable[[Settings], STTBatchProvider]):
        _stt_batch[provider_id] = RegisteredBatch(build, capabilities)
        return build

    return deco


def stt_stream_provider(provider_id: str) -> RegisteredStream | None:
    return _stt_stream.get(provider_id)


def stt_batch_provider(provider_id: str) -> RegisteredBatch | None:
    return _stt_batch.get(provider_id)
