"""Running statistics over a stream of round-trip times, some of them lost."""

from __future__ import annotations

import math
import time
from collections import deque


class RollingStats:
    """All-time counters and extremes, plus a window of recent samples for charts.

    A sample is a round-trip time in milliseconds, or None for a lost probe.
    """

    def __init__(self, window: int = 300) -> None:
        self.sent = 0
        self.received = 0
        self.last: float | None = None
        self.best: float | None = None
        self.worst: float | None = None
        self.jitter = 0.0   # RFC 3550 smoothed jitter, in ms
        self._mean = 0.0    # Welford's running mean and sum of squares
        self._m2 = 0.0
        self._prev: float | None = None
        # (time.time() the probe was sent, rtt or None), oldest first
        self.history: deque[tuple[float, float | None]] = deque(maxlen=window)

    def add(self, rtt_ms: float | None, sent_at: float | None = None) -> None:
        self.sent += 1
        self.history.append((time.time() if sent_at is None else sent_at, rtt_ms))
        if rtt_ms is None:
            return
        self.received += 1
        self.last = rtt_ms
        self.best = rtt_ms if self.best is None else min(self.best, rtt_ms)
        self.worst = rtt_ms if self.worst is None else max(self.worst, rtt_ms)
        delta = rtt_ms - self._mean
        self._mean += delta / self.received
        self._m2 += delta * (rtt_ms - self._mean)
        if self._prev is not None:
            self.jitter += (abs(rtt_ms - self._prev) - self.jitter) / 16
        self._prev = rtt_ms

    @property
    def lost(self) -> int:
        return self.sent - self.received

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.lost / self.sent if self.sent else 0.0

    @property
    def avg(self) -> float | None:
        return self._mean if self.received else None

    @property
    def stdev(self) -> float | None:
        if self.received < 2:
            return None
        return math.sqrt(self._m2 / (self.received - 1))

    def recent(self) -> list[float | None]:
        """Recent samples, oldest first, for sparklines and charts."""
        return [rtt for _, rtt in self.history]

    def percentile(self, p: float) -> float | None:
        """The p-th percentile (0-100) of the received samples in the window."""
        values = sorted(rtt for _, rtt in self.history if rtt is not None)
        if not values:
            return None
        rank = (len(values) - 1) * p / 100
        lo = math.floor(rank)
        hi = math.ceil(rank)
        return values[lo] + (values[hi] - values[lo]) * (rank - lo)
