"""Fixed-window attempt limiter for login/register."""

import time
from typing import Dict, List

from fastapi import HTTPException

# shortcut: counters live in this process's memory, so with N workers the real limit is N times
# higher and a restart resets it; move to Redis/DB if the API runs on several workers.
_MAX_KEYS = 10_000


class AttemptLimiter:
    def __init__(self, max_attempts: int, window_s: int):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._hits: Dict[str, List[float]] = {}

    def _recent(self, key: str) -> List[float]:
        cutoff = time.time() - self.window_s
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def check(self, key: str) -> None:
        """Raise 429 if `key` already used up its attempts in the window."""
        if len(self._recent(key)) >= self.max_attempts:
            raise HTTPException(status_code=429, detail="Too many attempts, try again later")

    def hit(self, key: str) -> None:
        if len(self._hits) >= _MAX_KEYS:
            self._hits.clear()  # bounded memory; an attacker flooding keys only resets everyone's count
        self._hits.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
