"""Streaming MP3 duration counter: walks frame headers, never decodes.

Every MPEG audio frame carries a fixed number of samples (1152 for MPEG-1
Layer III, 576 for MPEG-2/2.5 Layer III), so counting frames gives exact
duration without a decoder. ID3v2 tags are skipped. Bytes that are not a
valid frame header are skipped one at a time until sync is found again.
"""

_BITRATES = {  # kbps, Layer III
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


class Mp3DurationCounter:
    def __init__(self) -> None:
        self._buf = b""
        self._skip = 0  # bytes still to skip (frame body / ID3 tag)
        self.seconds = 0.0

    def feed(self, chunk: bytes) -> None:
        data = self._buf + chunk
        i = 0
        while True:
            if self._skip:
                step = min(self._skip, len(data) - i)
                i += step
                self._skip -= step
                if self._skip:
                    break
            if len(data) - i < 10:
                break
            if data[i:i + 3] == b"ID3":
                size = 0
                for byte in data[i + 6:i + 10]:
                    size = (size << 7) | (byte & 0x7F)
                self._skip = 10 + size
                continue
            header = data[i:i + 4]
            frame = _frame(header)
            if frame is None:
                i += 1
                continue
            length, seconds = frame
            self.seconds += seconds
            self._skip = length
        self._buf = data[i:]


def _frame(h: bytes) -> tuple[int, float] | None:
    if h[0] != 0xFF or (h[1] & 0xE0) != 0xE0:
        return None
    version = (h[1] >> 3) & 0x03  # 3=MPEG1, 2=MPEG2, 0=MPEG2.5, 1=reserved
    layer = (h[1] >> 1) & 0x03  # 1 = Layer III
    if version == 1 or layer != 1:
        return None
    bitrate_idx = h[2] >> 4
    rate_idx = (h[2] >> 2) & 0x03
    if rate_idx == 3 or bitrate_idx in (0, 15):
        return None
    padding = (h[2] >> 1) & 0x01
    rate = _RATES[version][rate_idx]
    bitrate = _BITRATES[1 if version == 3 else 2][bitrate_idx] * 1000
    samples = 1152 if version == 3 else 576
    length = samples // 8 * bitrate // rate + padding
    return length, samples / rate
