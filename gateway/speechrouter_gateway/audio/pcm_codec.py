"""Gateway-side wrappers around a provider's raw PCM output (PLAN §1.2).

No ffmpeg in the hot path: these are the only conversions the gateway does,
and each is cheap and streamable chunk by chunk.

- wav:   a 44-byte RIFF header in front of the PCM. The total length is not
         known while streaming, so the size fields carry 0xFFFFFFFF — the
         convention players (ffmpeg, browsers, sox) accept for live WAV.
- mulaw / alaw: G.711 encoding (ITU-T reference algorithm). audioop, which
         used to do this, was removed in Python 3.13.
- 24k -> 8k: integer decimation by 3 behind a windowed-sinc low-pass, for
         telephony output. Only integer ratios are supported.

Input is always signed 16-bit little-endian mono. Chunk boundaries may split
a sample or a decimation window; the converter carries the remainder.
"""

import math
import struct
import sys
from array import array

_UNKNOWN = 0xFFFFFFFF


def wav_header(sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    byte_rate = sample_rate * channels * bits // 8
    return (
        b"RIFF"
        + struct.pack("<I", _UNKNOWN)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, channels * bits // 8,
                      bits)
        + b"data"
        + struct.pack("<I", _UNKNOWN)
    )


_SEG_UEND = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)
_SEG_AEND = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)


def _segment(value: int, table: tuple[int, ...]) -> int:
    for i, end in enumerate(table):
        if value <= end:
            return i
    return len(table)


def _linear_to_ulaw(sample: int) -> int:
    """Sun g711.c linear2ulaw, 16-bit input."""
    value = sample >> 2
    if value < 0:
        value, mask = -value, 0x7F
    else:
        mask = 0xFF
    value = min(value, 8159) + (0x84 >> 2)
    seg = _segment(value, _SEG_UEND)
    if seg >= 8:
        return 0x7F ^ mask
    return ((seg << 4) | ((value >> (seg + 1)) & 0x0F)) ^ mask


def _linear_to_alaw(sample: int) -> int:
    """Sun g711.c linear2alaw, 16-bit input."""
    value = sample >> 3
    if value >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        value = -value - 1
    seg = _segment(value, _SEG_AEND)
    if seg >= 8:
        return 0x7F ^ mask
    shift = 1 if seg < 2 else seg
    return ((seg << 4) | ((value >> shift) & 0x0F)) ^ mask


# 65536-entry lookup tables: index = sample & 0xFFFF
_ULAW = bytes(_linear_to_ulaw(i - 65536 if i >= 32768 else i) for i in range(65536))
_ALAW = bytes(_linear_to_alaw(i - 65536 if i >= 32768 else i) for i in range(65536))


def _lowpass_taps(factor: int, n: int = 31) -> list[float]:
    """Hamming-windowed sinc, cutoff at the decimated Nyquist (0.9 margin)."""
    cutoff = 0.9 / factor / 2
    mid = (n - 1) / 2
    taps = []
    for i in range(n):
        x = i - mid
        sinc = 2 * cutoff if x == 0 else math.sin(2 * math.pi * cutoff * x) / (math.pi * x)
        taps.append(sinc * (0.54 - 0.46 * math.cos(2 * math.pi * i / (n - 1))))
    total = sum(taps)
    return [t / total for t in taps]


class PcmConverter:
    """Streaming s16le mono -> (resampled) pcm | mulaw | alaw | wav."""

    def __init__(self, target: str, src_rate: int, dst_rate: int):
        if target not in {"pcm", "wav", "mulaw", "alaw"}:
            raise ValueError(f"unsupported target {target}")
        if src_rate % dst_rate:
            raise ValueError(f"only integer decimation supported ({src_rate}->{dst_rate})")
        self._target = target
        self._factor = src_rate // dst_rate
        self._dst_rate = dst_rate
        self._odd = b""  # a split sample from the previous chunk
        self._taps = _lowpass_taps(self._factor) if self._factor > 1 else []
        # filter state, primed with half a window of silence so output k is
        # centred on input k*factor (no dropped head); flush() drains the tail
        self._history: list[int] = [0] * (len(self._taps) // 2)
        self._phase = 0
        self._header_sent = False

    def feed(self, chunk: bytes) -> bytes:
        data = self._odd + chunk
        cut = len(data) - (len(data) % 2)
        self._odd = data[cut:]
        samples = array("h")
        samples.frombytes(data[:cut])
        if sys.byteorder == "big":
            samples.byteswap()
        if self._factor > 1:
            samples = self._decimate(samples)
        out = self._encode(samples)
        if self._target == "wav" and not self._header_sent:
            self._header_sent = True
            return wav_header(self._dst_rate) + out
        return out

    def _decimate(self, samples: array) -> array:
        taps = self._taps
        n = len(taps)
        buf = self._history + samples.tolist()
        out = array("h")
        # output sample k uses buf[i-n+1 .. i] where i steps by factor
        i = n - 1 + self._phase
        while i < len(buf):
            acc = 0.0
            base = i - n + 1
            for j in range(n):
                acc += taps[j] * buf[base + j]
            out.append(max(-32768, min(32767, int(round(acc)))))
            i += self._factor
        self._phase = i - len(buf)
        self._history = buf[-(n - 1):] if n > 1 else []
        return out

    def _encode(self, samples: array) -> bytes:
        if self._target in {"pcm", "wav"}:
            if sys.byteorder == "big":
                samples.byteswap()
            return samples.tobytes()
        table = _ULAW if self._target == "mulaw" else _ALAW
        return bytes(table[s & 0xFFFF] for s in samples)

    def flush(self) -> bytes:
        out = b""
        if self._factor > 1:
            tail = array("h", [0] * (len(self._taps) // 2))
            out = self._encode(self._decimate(tail))
        if self._target == "wav" and not self._header_sent:
            self._header_sent = True
            return wav_header(self._dst_rate) + out
        return out


def pcm_seconds(byte_count: int, sample_rate: int) -> float:
    return byte_count / (2 * sample_rate)
