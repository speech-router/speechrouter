import asyncio

from speechrouter_gateway.audio import AudioRing, bytes_per_second


def test_bytes_per_second():
    assert bytes_per_second("linear16", 16000) == 32000
    assert bytes_per_second("mulaw", 8000) == 8000
    assert bytes_per_second("linear32", 16000, channels=2) == 128000
    assert bytes_per_second("opus", 48000) is None


async def test_append_tracks_audio_time_and_iterates():
    ring = AudioRing(max_seconds=10, byte_rate=32000)
    await ring.append(b"\x00" * 32000)  # 1.0s
    await ring.append(b"\x00" * 16000)  # 0.5s
    await ring.close()
    assert ring.audio_seconds == 1.5
    chunks = [c async for c in ring.iter_from(0)]
    assert [c.start for c in chunks] == [0.0, 1.0]
    assert [c.duration for c in chunks] == [1.0, 0.5]


async def test_trim_drops_old_and_iter_skips_forward():
    ring = AudioRing(max_seconds=2, byte_rate=32000)
    for _ in range(5):  # 5 seconds total, keeps ~last 2s
        await ring.append(b"\x00" * 32000)
    await ring.close()
    idx, start = ring.replay_start()
    assert start >= 2.0  # oldest retained is within the window
    chunks = [c async for c in ring.iter_from(0)]  # asks from trimmed region
    assert chunks[0].idx == idx  # skipped forward, no crash


async def test_iter_waits_for_new_audio_then_ends_on_close():
    ring = AudioRing(max_seconds=10, byte_rate=32000)
    collected = []

    async def consume():
        async for chunk in ring.iter_from(0):
            collected.append(chunk.idx)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await ring.append(b"\x00" * 100)
    await asyncio.sleep(0.01)
    await ring.append(b"\x00" * 100)
    await ring.close()
    await asyncio.wait_for(task, 1.0)
    assert collected == [0, 1]


async def test_append_after_close_is_ignored():
    ring = AudioRing(max_seconds=10, byte_rate=32000)
    await ring.close()
    await ring.append(b"\x00" * 32000)
    assert ring.audio_seconds == 0.0
