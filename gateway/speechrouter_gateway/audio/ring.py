"""Session audio ring buffer.

Single source of audio truth for a streaming session: the client reader
appends, the provider feeder iterates by index. Failover replays by starting
a new iteration at the oldest retained chunk — the buffer keeps the last
`max_seconds` of audio, so a mid-stream provider switch can re-transcribe
recent context (the spec's ring-buffer replay).

Audio time is derived from byte counts for raw PCM-family encodings and from
wall-clock arrival gaps for opaque codecs (opus etc.), capped so network
stalls don't inflate the clock.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass


def bytes_per_second(encoding: str, sample_rate: int, channels: int = 1) -> int | None:
    """Bytes of audio per second, None when the codec makes it unknowable."""
    per_sample = {"linear16": 2, "linear32": 4, "mulaw": 1, "alaw": 1}.get(encoding)
    if per_sample is None:
        return None
    return sample_rate * per_sample * channels


@dataclass(frozen=True)
class Chunk:
    idx: int
    data: bytes
    start: float  # session audio-time seconds
    duration: float


class AudioRing:
    def __init__(self, max_seconds: float, byte_rate: int | None):
        self._max_seconds = max_seconds
        self._byte_rate = byte_rate
        self._chunks: deque[Chunk] = deque()
        self._next_idx = 0
        self._clock = 0.0  # total audio seconds ever appended
        self._last_wall: float | None = None
        self._closed = False
        self._cond = asyncio.Condition()

    @property
    def audio_seconds(self) -> float:
        return self._clock

    @property
    def closed(self) -> bool:
        return self._closed

    async def append(self, data: bytes) -> None:
        if self._byte_rate:
            duration = len(data) / self._byte_rate
        else:
            now = time.monotonic()
            duration = 0.0 if self._last_wall is None else min(now - self._last_wall, 1.0)
            self._last_wall = now
        async with self._cond:
            if self._closed:
                return
            self._chunks.append(Chunk(self._next_idx, data, self._clock, duration))
            self._next_idx += 1
            self._clock += duration
            while self._chunks and self._clock - self._chunks[0].start > self._max_seconds:
                self._chunks.popleft()
            self._cond.notify_all()

    async def close(self) -> None:
        """No more audio will arrive; iterators finish once drained."""
        async with self._cond:
            self._closed = True
            self._cond.notify_all()

    def replay_start(self) -> tuple[int, float]:
        """(idx, session audio-time) of the oldest retained chunk — where a
        replacement provider resumes."""
        if self._chunks:
            first = self._chunks[0]
            return first.idx, first.start
        return self._next_idx, self._clock

    async def iter_from(self, idx: int):
        """Yield chunks with .idx >= idx; waits for new audio; ends when the
        ring is closed and drained. Skips forward past trimmed chunks."""
        while True:
            async with self._cond:
                chunk = self._get(idx)
                while chunk is None:
                    if self._closed and idx >= self._next_idx:
                        return
                    await self._cond.wait()
                    chunk = self._get(idx)
            yield chunk
            idx = chunk.idx + 1

    def _get(self, idx: int) -> Chunk | None:
        if not self._chunks or idx >= self._next_idx:
            return None
        first_idx = self._chunks[0].idx
        if idx < first_idx:
            idx = first_idx  # requested audio was trimmed; resume at oldest retained
        return self._chunks[idx - first_idx]
