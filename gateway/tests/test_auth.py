from speechrouter_gateway.auth import build_keystore
from speechrouter_gateway.config import KeyStoreKind, Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


async def test_local_keystore_accepts_configured_keys():
    ks = build_keystore(_settings(keystore=KeyStoreKind.local, keys="sk_a, sk_b"))
    assert await ks.lookup("sk_a") is not None
    assert await ks.lookup("sk_b") is not None


async def test_local_keystore_rejects_unknown_and_empty():
    ks = build_keystore(_settings(keystore=KeyStoreKind.local, keys="sk_a"))
    assert await ks.lookup("sk_wrong") is None
    assert await ks.lookup("") is None


async def test_none_keystore_allows_anything():
    ks = build_keystore(_settings(keystore=KeyStoreKind.none))
    assert await ks.lookup("whatever") is not None
