"""Minimal per-source rate limiting (minimum spacing between calls)."""
from __future__ import annotations

import threading
import time


class RateLimiter:
    """Block so that consecutive ``wait()`` calls are at least ``min_interval`` apart."""

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        if min_interval < 0:
            raise ValueError("min_interval must be >= 0")
        self.min_interval = float(min_interval)
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Sleep if needed; return the number of seconds slept."""
        with self._lock:
            now = self._clock()
            slept = 0.0
            if self._last is not None:
                gap = self.min_interval - (now - self._last)
                if gap > 0:
                    self._sleep(gap)
                    slept = gap
                    now = self._clock()
            self._last = now
            return slept


# Shared limiters per upstream. Public APIs, be polite.
LIMITERS = {
    "open_meteo": RateLimiter(0.2),
    "nws": RateLimiter(0.5),
    "kalshi": RateLimiter(0.2),
    "fred": RateLimiter(0.5),
    "ghcn": RateLimiter(1.0),
    "yfinance": RateLimiter(1.0),
}
