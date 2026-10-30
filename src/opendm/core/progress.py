"""Speed and ETA calculation. Clocks are injectable so tests never sleep."""

import time
from collections import deque
from collections.abc import Callable

Clock = Callable[[], float]


class SpeedMeter:
    """Average speed over a sliding time window, from cumulative byte counts."""

    def __init__(self, window: float = 3.0, clock: Clock = time.monotonic) -> None:
        self._window = window
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque()
        self.total = 0

    def reset(self, total: int = 0) -> None:
        """Start measuring from ``total`` bytes (non-zero when resuming)."""
        self._samples.clear()
        self.total = total
        self._samples.append((self._clock(), total))

    def update(self, total: int) -> None:
        self.total = total
        self._samples.append((self._clock(), total))
        self._prune(self._clock())

    def speed(self) -> float:
        now = self._clock()
        self._prune(now)
        first_t, first_total = self._samples[0]
        elapsed = now - first_t
        if elapsed <= 0:
            return 0.0
        return (self.total - first_total) / elapsed

    def _prune(self, now: float) -> None:
        horizon = now - self._window
        while len(self._samples) > 1 and self._samples[1][0] <= horizon:
            self._samples.popleft()
        # A single stale sample means nothing arrived during the window.
        if len(self._samples) == 1 and self._samples[0][0] < horizon:
            self._samples[0] = (horizon, self.total)


def eta_seconds(total: int | None, done: int, speed: float) -> float | None:
    if total is None or speed <= 0:
        return None
    return max(total - done, 0) / speed


class Throttle:
    """Rate-limits progress events (the GUI only needs ~4 Hz)."""

    def __init__(self, interval: float = 0.25, clock: Clock = time.monotonic) -> None:
        self._interval = interval
        self._clock = clock
        self._last: float | None = None

    def ready(self) -> bool:
        now = self._clock()
        if self._last is None or now - self._last >= self._interval:
            self._last = now
            return True
        return False
