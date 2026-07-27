"""Model-based adapter dispatch for providers with multiple wire protocols.

Deepgram flux-* models speak the v2 turn protocol while nova-* speak v1;
Cartesia ink-2-turns uses the turns endpoint while other models use the
classic WS. The registry is keyed by provider id, so a dispatcher picks the
concrete implementation once the model is known (at connect time)."""

from collections.abc import AsyncIterator, Callable

from .base import Capabilities, ProviderStreamError, STTConfig, STTEvent, STTStreamProvider


class ModelDispatchStream(STTStreamProvider):
    def __init__(
        self,
        name: str,
        capabilities: Capabilities,
        chooser: Callable[[STTConfig], tuple[STTStreamProvider, STTConfig]],
    ):
        self.name = name
        self.capabilities = capabilities
        self._chooser = chooser
        self._impl: STTStreamProvider | None = None

    async def connect(self, config: STTConfig) -> None:
        impl, effective_config = self._chooser(config)
        self._impl = impl
        await impl.connect(effective_config)

    async def send_audio(self, chunk: bytes) -> None:
        assert self._impl is not None
        await self._impl.send_audio(chunk)

    def events(self) -> AsyncIterator[STTEvent]:
        if self._impl is None:
            raise ProviderStreamError(
                "events before connect", recoverable=False, provider=self.name
            )
        return self._impl.events()

    async def finish(self) -> None:
        if self._impl is not None:
            await self._impl.finish()

    async def close(self) -> None:
        if self._impl is not None:
            await self._impl.close()
