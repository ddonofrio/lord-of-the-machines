from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class TokenRateLimitReservation:
    token_count: int
    capacity: int
    used_before: int
    wait_seconds: float
    attempts: int
    oversized: bool = False


class TokenRateLimiter:
    def __init__(
        self,
        *,
        tokens_per_window: int,
        window_seconds: float = 60.0,
        safety_margin_tokens: int = 0,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.tokens_per_window = max(0, int(tokens_per_window))
        self.window_seconds = max(0.001, float(window_seconds))
        self.safety_margin_tokens = max(0, int(safety_margin_tokens))
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._reservations: list[tuple[float, int]] = []
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return max(0, self.tokens_per_window - self.safety_margin_tokens)

    def reserve(self, token_count: int) -> TokenRateLimitReservation:
        token_count = max(0, int(token_count))
        capacity = self.capacity
        if token_count <= 0 or capacity <= 0:
            return TokenRateLimitReservation(
                token_count=token_count,
                capacity=capacity,
                used_before=0,
                wait_seconds=0.0,
                attempts=0,
                oversized=token_count > capacity,
            )

        total_wait = 0.0
        attempts = 0
        while True:
            with self._lock:
                now = self._clock()
                self._prune(now)
                used = self._used_tokens()
                oversized = token_count > capacity
                if oversized and used <= 0:
                    self._reservations.append((now, capacity))
                    return TokenRateLimitReservation(token_count, capacity, used, total_wait, attempts, True)
                if not oversized and used + token_count <= capacity:
                    self._reservations.append((now, token_count))
                    return TokenRateLimitReservation(token_count, capacity, used, total_wait, attempts, False)
                wait_seconds = self._seconds_until_next_expiration(now)

            if wait_seconds <= 0:
                continue
            attempts += 1
            self._sleeper(wait_seconds)
            total_wait += wait_seconds

    def _prune(self, now: float) -> None:
        self._reservations = [
            (timestamp, tokens)
            for timestamp, tokens in self._reservations
            if timestamp + self.window_seconds > now
        ]

    def _used_tokens(self) -> int:
        return sum(tokens for _, tokens in self._reservations)

    def _seconds_until_next_expiration(self, now: float) -> float:
        if not self._reservations:
            return 0.0
        oldest_timestamp = min(timestamp for timestamp, _ in self._reservations)
        return max(0.0, oldest_timestamp + self.window_seconds - now)
