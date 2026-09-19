from __future__ import annotations

import threading


class AttemptsExhaustedError(Exception):
    pass


class AttemptTracker:
    def __init__(self, max_attempts: int = 5):
        self._max_attempts = max_attempts
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def record_attempt(self, issue_key: str) -> int:
        with self._lock:
            count = self._counts.get(issue_key, 0) + 1
            self._counts[issue_key] = count
            return count

    def attempts_remaining(self, issue_key: str) -> int:
        with self._lock:
            return max(0, self._max_attempts - self._counts.get(issue_key, 0))

    def is_exhausted(self, issue_key: str) -> bool:
        return self.attempts_remaining(issue_key) <= 0
