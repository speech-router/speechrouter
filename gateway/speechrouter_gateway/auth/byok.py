"""BYOK: orgs can route with their own provider credentials.

Contract with the cloud app (Rails is the writer of record):
- On save:   SET speechrouter:byok:<org_id>:<provider> -> plaintext provider key
- On remove: DEL speechrouter:byok:<org_id>:<provider>

When a request's org has a key for the resolved provider, the gateway swaps
it into a per-request Settings copy before building the adapter and flags the
usage event, so billing charges the routing fee instead of full list price.
Providers with multi-field credentials (aws, azure, google) are not BYOK-able
yet. A Redis hiccup falls back to house keys — availability over discounts.
"""

from typing import Any

BYOK_PREFIX = "speechrouter:byok:"
BLOCKED_PREFIX = "speechrouter:blocked:"

PROVIDER_KEY_FIELDS = {
    "deepgram": "deepgram_api_key",
    "soniox": "soniox_api_key",
    "assemblyai": "assemblyai_api_key",
    "speechmatics": "speechmatics_api_key",
    "openai": "openai_api_key",
    "groq": "groq_api_key",
    "mistral": "mistral_api_key",
    "cartesia": "cartesia_api_key",
    "elevenlabs": "elevenlabs_api_key",
}


async def org_blocked(redis: Any, org_id: str | None) -> bool:
    """Cloud writes speechrouter:blocked:<org> when the balance hits zero.
    New sessions are rejected; in-flight streams are allowed to finish.
    A Redis hiccup fails OPEN — availability over enforcement."""
    if redis is None or not org_id:
        return False
    try:
        return await redis.get(f"{BLOCKED_PREFIX}{org_id}") is not None
    except Exception:
        return False


async def apply_byok(settings: Any, redis: Any, org_id: str | None, providers: set[str]):
    """Return (settings, byok_used) with org-supplied keys swapped in."""
    if redis is None or not org_id:
        return settings, False
    updates: dict[str, str] = {}
    for provider in providers:
        field = PROVIDER_KEY_FIELDS.get(provider)
        if field is None:
            continue
        try:
            key = await redis.get(f"{BYOK_PREFIX}{org_id}:{provider}")
        except Exception:
            key = None
        if key:
            updates[field] = key
    if not updates:
        return settings, False
    return settings.model_copy(update=updates), True
