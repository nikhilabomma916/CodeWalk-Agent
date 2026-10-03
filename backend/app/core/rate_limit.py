"""In-process sliding-window counter for failed login attempts.

State lives in this process only: with several API workers each keeps its own
counts (an attacker gets ``workers x limit`` attempts). A shared store such as
Redis would be needed for a strict global limit.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class AttemptLimiter:
    def __init__(self, max_attempts: int, window_seconds: float, *, max_keys: int = 100_000) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.get(key)
        if attempts is None:
            return deque()
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        if not attempts:
            del self._attempts[key]
        return attempts

    def retry_after(self, key: str) -> int | None:
        """Seconds until another attempt is allowed, or None when not limited."""
        now = time.monotonic()
        with self._lock:
            attempts = self._recent(key, now)
            if len(attempts) < self.max_attempts:
                return None
            return max(1, int(attempts[0] + self.window_seconds - now) + 1)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if key not in self._attempts and len(self._attempts) >= self.max_keys:
                # Bound memory: drop the oldest key (dicts keep insertion order).
                self._attempts.pop(next(iter(self._attempts)))
            attempts = self._attempts.setdefault(key, deque())
            attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
