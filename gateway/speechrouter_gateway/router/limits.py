"""Per-org concurrent stream cap — blast-radius insurance.

A leaked key must not be able to open unbounded parallel streams and run
up provider bills. The guard counts live streaming sessions per scope
(org in cloud mode, key in local mode) inside this process; acquire/release
wrap the session lifecycle so crashes can't leak slots.

Scope note: process-local by design. Behind a load balancer each instance
enforces the cap independently (N instances => N x cap worst case); a
Redis-based global counter replaces this when we scale out.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class ConcurrencyGuard:
    limit: int
    _counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _lock: Lock = field(default_factory=Lock)

    def acquire(self, scope: str) -> bool:
        if self.limit <= 0:
            return True  # 0 = unlimited (self-host default freedom)
        with self._lock:
            if self._counts[scope] >= self.limit:
                return False
            self._counts[scope] += 1
            return True

    def release(self, scope: str) -> None:
        if self.limit <= 0:
            return
        with self._lock:
            self._counts[scope] = max(0, self._counts[scope] - 1)
            if self._counts[scope] == 0:
                del self._counts[scope]

    def active(self, scope: str) -> int:
        with self._lock:
            return self._counts.get(scope, 0)
