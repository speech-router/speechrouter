"""Provider-failure alerting.

An upstream failure — our Deepgram key revoked, a vendor account out of
credits, a provider outage — must reach a human, not just the logs. When
Sentry is configured, every provider failure becomes an issue fingerprinted
per (provider, code): one broken key groups into ONE alert that emails the
founders, instead of one event per dying session.
"""

from .logging import logger


def report_provider_failure(
    provider: str | None, model: str, message: str, *, code: str | None = None
) -> None:
    logger.error(
        "provider failure",
        extra={"provider": provider, "model": model, "code": code, "detail": message},
    )
    try:
        import sentry_sdk  # noqa: PLC0415 - optional dependency path

        if sentry_sdk.get_client().is_active():
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("provider", provider or "unknown")
                scope.set_tag("model", model)
                scope.set_tag("code", code or "provider_error")
                scope.fingerprint = ["provider-failure", provider or "unknown", code or ""]
                sentry_sdk.capture_message(
                    f"provider failure [{provider}]: {message[:200]}", level="error"
                )
    except Exception:  # noqa: BLE001, S110 - alerting must never break the data path
        pass
