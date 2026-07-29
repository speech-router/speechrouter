"""Short-lived client tokens: mint, authenticate, expire."""

import time

from test_cloud_contracts import FakeRedis

from speechrouter_gateway.auth.keystore import KeyRecord
from speechrouter_gateway.auth.tokens import (
    REDIS_PREFIX,
    LocalTokenStore,
    RedisTokenStore,
    is_token,
    resolve_credentials,
)


async def test_local_store_mints_and_expires(monkeypatch):
    store = LocalTokenStore()
    record = KeyRecord(key_id="42", org_id="7")
    token, expires_at = await store.mint(record, 60)

    assert is_token(token)
    assert expires_at > time.time()
    found = await store.lookup(token)
    assert found is not None and found.key_id == "42" and found.org_id == "7"
    assert await store.lookup("st_nope") is None

    # fast-forward past expiry
    monkeypatch.setattr(time, "time", lambda: expires_at + 1)
    assert await store.lookup(token) is None


async def test_redis_store_round_trip_and_ttl():
    fake = FakeRedis()
    store = RedisTokenStore(fake)
    token, _ = await store.mint(KeyRecord(key_id="9", org_id="3"), 45)

    found = await store.lookup(token)
    assert found is not None and found.key_id == "9" and found.org_id == "3"
    # stored hashed, never plaintext, with a TTL
    (stored_key,) = [k for k in fake.kv if k.startswith(REDIS_PREFIX)]
    assert token not in stored_key
    assert fake.ttls[stored_key] == 45

    fake.fail = True
    assert await store.lookup(token) is None  # outage -> deny, don't crash


async def test_resolve_credentials_dispatches():
    class State:
        pass

    state = State()
    state.token_store = LocalTokenStore()
    token, _ = await state.token_store.mint(KeyRecord(key_id="t1"), 60)

    class KS:
        async def lookup(self, presented):
            return KeyRecord(key_id="k1") if presented == "sk_real" else None

    state.keystore = KS()

    assert (await resolve_credentials(state, token)).key_id == "t1"
    assert (await resolve_credentials(state, "sk_real")).key_id == "k1"
    assert await resolve_credentials(state, "st_expired_or_fake") is None
