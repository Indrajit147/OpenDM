"""Token-bucket speed limiting (global and per download)."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable

from opendm.core.progress import Clock

BURST_SECONDS = 0.1  # keep bursts small so the limit holds over short windows


class TokenBucket:
    """Limits throughput to ``rate`` bytes/s; ``None`` or 0 means unlimited.

    Starts empty and lets the balance go negative: a caller pays its debt by
    sleeping, so concurrent callers share the rate without busy-waiting.
    """

    def __init__(
        self,
        rate: float | None,
        *,
        clock: Clock = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._tokens = 0.0
        self._last = clock()
        self._rate: float | None = None
        self.rate = rate

    @property
    def rate(self) -> float | None:
        return self._rate

    @rate.setter
    def rate(self, value: float | None) -> None:
        if value is not None and value < 0:
            raise ValueError("rate must be positive or None")
        self._refill()
        self._rate = value or None
        self._tokens = min(self._tokens, self._capacity())

    def _capacity(self) -> float:
        return (self._rate or 0) * BURST_SECONDS

    def _refill(self) -> None:
        now = self._clock()
        if self._rate:
            self._tokens = min(self._capacity(), self._tokens + (now - self._last) * self._rate)
        self._last = now

    async def acquire(self, nbytes: int) -> None:
        if not self._rate:
            return
        self._refill()
        self._tokens -= nbytes
        if self._tokens < 0:
            await self._sleep(-self._tokens / self._rate)


async def acquire_all(buckets: Iterable[TokenBucket | None], nbytes: int) -> None:
    for bucket in buckets:
        if bucket is not None:
            await bucket.acquire(nbytes)
