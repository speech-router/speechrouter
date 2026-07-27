"""Batch response formatting: normalized Transcript -> OpenAI-compatible bodies.

srt/vtt are synthesized from word timings here, so every provider gets them
even when the upstream doesn't offer subtitle formats (e.g. Groq)."""

from ..protocol import Transcript, Word

MAX_CUE_WORDS = 12
MAX_CUE_SECONDS = 5.0
CUE_GAP_SECONDS = 1.0


def to_json(transcript: Transcript) -> dict:
    return {"text": transcript.text}


def to_verbose_json(transcript: Transcript, model_slug: str) -> dict:
    words = transcript.words or []
    duration = transcript.end if transcript.end is not None else (
        words[-1].end if words else 0.0
    )
    return {
        "task": "transcribe",
        "language": transcript.lang,
        "duration": duration,
        "text": transcript.text,
        "words": [
            {"word": w.w, "start": w.start, "end": w.end}
            | ({"speaker": w.speaker} if w.speaker is not None else {})
            for w in words
        ],
        "model": model_slug,
    }


def _cues(words: list[Word]) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    current: list[Word] = []
    for word in words:
        if current and (
            len(current) >= MAX_CUE_WORDS
            or word.end - current[0].start > MAX_CUE_SECONDS
            or word.start - current[-1].end > CUE_GAP_SECONDS
        ):
            cues.append((current[0].start, current[-1].end, " ".join(w.w for w in current)))
            current = []
        current.append(word)
    if current:
        cues.append((current[0].start, current[-1].end, " ".join(w.w for w in current)))
    return cues


def _stamp(seconds: float, *, comma: bool) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(transcript: Transcript) -> str:
    words = transcript.words or []
    if not words:  # no timings anywhere: single cue with the full text
        return f"1\n00:00:00,000 --> 00:00:05,000\n{transcript.text}\n" if transcript.text else ""
    lines = []
    for i, (start, end, text) in enumerate(_cues(words), 1):
        lines.append(
            f"{i}\n{_stamp(start, comma=True)} --> {_stamp(end, comma=True)}\n{text}\n"
        )
    return "\n".join(lines)


def to_vtt(transcript: Transcript) -> str:
    words = transcript.words or []
    out = ["WEBVTT", ""]
    if not words:
        if transcript.text:
            out.append(f"00:00:00.000 --> 00:00:05.000\n{transcript.text}\n")
        return "\n".join(out)
    for start, end, text in _cues(words):
        out.append(f"{_stamp(start, comma=False)} --> {_stamp(end, comma=False)}\n{text}\n")
    return "\n".join(out)
