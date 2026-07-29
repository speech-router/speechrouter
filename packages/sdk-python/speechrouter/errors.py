from __future__ import annotations


class SpeechRouterError(Exception):
    """Every failure the SDK surfaces.

    `code` is the gateway's machine-readable error enum, or a client-side
    code ("connection_failed", "connection_closed", "timeout").
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status: int | None = None,
        provider: str | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.provider = provider
        self.recoverable = recoverable

    def __repr__(self) -> str:  # pragma: no cover - debugging nicety
        return f"SpeechRouterError(code={self.code!r}, message={self.args[0]!r})"
