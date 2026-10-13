"""Secret scrubbing for live-probe output (prints, JSON summaries, frame logs).

Vendor errors can echo a key, or a masked fragment of one (OpenAI prints
`sk-proj-****abcd`). Everything a probe prints or writes goes through scrub():
  1. every loaded secret value is replaced, wherever it appears;
  2. key-shaped tokens and masked fragments are replaced by pattern.
"""

import re

_PATTERNS = [
    re.compile(r"\b(sk|gsk|xai|sk_car|sk-proj|sk-ant|AIza|dg|ak|key)[-_][A-Za-z0-9*_\-]{6,}"),
    re.compile(r"\*{3,}[A-Za-z0-9_\-]{0,12}"),  # masked tails like ****abcd
    re.compile(r"(?i)\b(api[_-]?key|key|token|secret|authorization)([\"'\s:=]+(?:(?:Bearer|Token|Basic)\s+)?)([A-Za-z0-9._\-]{12,})"),
]


def scrub(text: str, secrets: list[str]) -> str:
    for secret in sorted((s for s in secrets if len(s) >= 6), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    for pattern in _PATTERNS[:2]:
        text = pattern.sub("[REDACTED]", text)
    return _PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
