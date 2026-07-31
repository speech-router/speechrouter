"""Cloud keystore + redis emitter against an in-memory fake Redis."""

import hashlib
import json

from speechrouter_gateway.auth.cloud_store import KEY_PREFIX, CloudKeyStore
from speechrouter_gateway.metering.emitter import UsageEvent
from speechrouter_gateway.metering.redis_emitter import USAGE_STREAM, RedisUsageEmitter


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.streams: dict[str, list[dict]] = {}
        self.fail = False

    async def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.kv.get(key)

    async def set(self, key, value, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.kv[key] = value
        if ex is not None:
            self.ttls[key] = ex

    async def xadd(self, stream, fields, **_kw):
        if self.fail:
            raise ConnectionError("redis down")
        self.streams.setdefault(stream, []).append(fields)


async def test_lookup_hits_and_misses():
    fake = FakeRedis()
    plaintext = "sk_sr_abc123"
    digest = hashlib.sha256(plaintext.encode()).hexdigest()
    fake.kv[f"{KEY_PREFIX}{digest}"] = json.dumps({"key_id": "42", "org_id": "7"})
    store = CloudKeyStore("redis://unused", client=fake)  # type: ignore[arg-type]

    record = await store.lookup(plaintext)
    assert record is not None and record.key_id == "42" and record.org_id == "7"
    assert await store.lookup("sk_sr_wrong") is None
    assert await store.lookup("") is None


async def test_lookup_survives_redis_outage():
    fake = FakeRedis()
    fake.fail = True
    store = CloudKeyStore("redis://unused", client=fake)  # type: ignore[arg-type]
    assert await store.lookup("sk_sr_abc") is None  # deny, don't crash


async def test_emitter_writes_stream_and_swallows_failures():
    fake = FakeRedis()
    emitter = RedisUsageEmitter("redis://unused", client=fake)  # type: ignore[arg-type]
    event = UsageEvent(session_id="s1", key_id="42", model="deepgram/nova-3",
                       kind="stt_stream", audio_seconds=8.5)
    await emitter.emit(event)
    payload = json.loads(fake.streams[USAGE_STREAM][0]["payload"])
    assert payload["session_id"] == "s1" and payload["audio_seconds"] == 8.5

    fake.fail = True
    await emitter.emit(event)  # must not raise


async def test_apply_byok_overrides_settings_and_flags():
    from speechrouter_gateway.auth.byok import BYOK_PREFIX, apply_byok
    from speechrouter_gateway.config import Settings

    settings = Settings(deepgram_api_key="house-key", _env_file=None)
    fake = FakeRedis()
    fake.kv[f"{BYOK_PREFIX}7:deepgram"] = "org-own-key"

    # Org 7 brought a Deepgram key: swapped in, flagged, original untouched.
    patched, used = await apply_byok(settings, fake, "7", {"deepgram"})
    assert used and patched.deepgram_api_key == "org-own-key"
    assert settings.deepgram_api_key == "house-key"

    # No key stored for this provider -> house keys, not flagged.
    _, used = await apply_byok(settings, fake, "7", {"soniox"})
    assert not used

    # Multi-field providers are not BYOK-able; anonymous/local mode passes through.
    _, used = await apply_byok(settings, fake, "7", {"aws"})
    assert not used
    _, used = await apply_byok(settings, fake, None, {"deepgram"})
    assert not used

    # Redis outage falls back to house keys instead of failing the stream.
    fake.fail = True
    patched, used = await apply_byok(settings, fake, "7", {"deepgram"})
    assert not used and patched.deepgram_api_key == "house-key"


async def test_usage_event_carries_byok_flag():
    fake = FakeRedis()
    emitter = RedisUsageEmitter("redis://unused", client=fake)  # type: ignore[arg-type]
    await emitter.emit(UsageEvent(session_id="s2", key_id="42", model="deepgram/nova-3",
                                  kind="stt_stream", audio_seconds=1.0, byok=True))
    payload = json.loads(fake.streams[USAGE_STREAM][0]["payload"])
    assert payload["byok"] is True


async def test_org_blocked_flag():
    from speechrouter_gateway.auth.byok import BLOCKED_PREFIX, org_blocked

    fake = FakeRedis()
    assert not await org_blocked(fake, "7")          # no flag -> allowed
    fake.kv[f"{BLOCKED_PREFIX}7"] = "1"
    assert await org_blocked(fake, "7")              # broke -> blocked
    assert not await org_blocked(fake, None)         # local mode -> never
    fake.fail = True
    assert not await org_blocked(fake, "7")          # redis down -> fail open


async def test_usage_event_carries_billing_fields():
    fake = FakeRedis()
    emitter = RedisUsageEmitter("redis://unused", client=fake)  # type: ignore[arg-type]
    await emitter.emit(UsageEvent(
        session_id="s3", key_id="1", model="soniox/stt-rt-v5", kind="stt_stream",
        audio_seconds=10.0, billed_seconds=42.5, billing_basis="session_time",
    ))
    payload = json.loads(fake.streams[USAGE_STREAM][0]["payload"])
    assert payload["billed_seconds"] == 42.5
    assert payload["billing_basis"] == "session_time"
