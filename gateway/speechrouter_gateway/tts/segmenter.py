"""Sentence segmentation for /v1/speak over request/response TTS vendors.

OpenAI and Gemini TTS take whole text per request, while voice agents
stream LLM tokens. The segmenter turns `text.delta` fragments into
synthesis units (PLAN §1.1 B):

- Cut after a sentence terminator followed by whitespace (". ! ? ; :" and
  the closing quotes/brackets that may trail them), immediately after CJK
  terminators (。！？；), and at newlines.
- Never emit a segment shorter than `min_chars` (it merges into the next),
  except on flush. Very short requests sound clipped and cost a round trip.
- `max_chars` forces a cut at the last whitespace (vendor input limits).
- `take_stale()` lets the session cut a long pending clause at a word
  boundary when the producer pauses, so audio doesn't wait on a sentence
  end that is slow to arrive.
"""

import re

_TERMINATOR = re.compile(r"[.!?;:…]+[\"'”’)\]]*\s+|[。！？；]+|\n+")


class TextSegmenter:
    def __init__(self, min_chars: int = 20, max_chars: int = 4096):
        self._buf = ""
        self._min = min_chars
        self._max = max_chars

    @property
    def pending(self) -> str:
        return self._buf

    def push(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        while True:
            cut = self._next_cut()
            if cut is None:
                break
            segment, self._buf = self._buf[:cut], self._buf[cut:]
            if segment.strip():
                out.append(segment.strip())
        return out

    def _next_cut(self) -> int | None:
        for match in _TERMINATOR.finditer(self._buf):
            if match.end() > self._max:
                break  # too far: fall through to the forced word-boundary cut
            if match.end() >= self._min:
                return match.end()
        if len(self._buf) > self._max:
            space = self._buf.rfind(" ", 0, self._max)
            return space + 1 if space > 0 else self._max
        return None

    def take_stale(self) -> str | None:
        """Cut pending text at its last word boundary (producer paused)."""
        if len(self._buf) < self._min:
            return None
        space = self._buf.rstrip().rfind(" ")
        if space <= 0:
            return None
        segment, self._buf = self._buf[:space], self._buf[space + 1:]
        return segment.strip() or None

    def flush(self) -> str | None:
        segment, self._buf = self._buf.strip(), ""
        return segment or None

    def clear(self) -> None:
        self._buf = ""
