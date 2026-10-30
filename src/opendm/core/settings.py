"""Engine tuning knobs. Defaults follow spec 6.1."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

MIB = 1024 * 1024
MAX_CONNECTIONS = 32


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with full jitter for retryable errors."""

    max_retries: int = 5
    base_delay: float = 1.0
    factor: float = 2.0
    max_delay: float = 30.0
    max_retry_after: float = 60.0  # cap on a server's Retry-After

    def delay(self, attempt: int, rng: Callable[[], float] = random.random) -> float:
        """Seconds to wait before retry number ``attempt`` (0-based)."""
        ceiling = min(self.max_delay, self.base_delay * self.factor**attempt)
        return rng() * ceiling

    def wait_for(
        self, attempt: int, retry_after: float | None, rng: Callable[[], float] = random.random
    ) -> float:
        """A server's Retry-After (capped) wins over our own backoff."""
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_retry_after)
        return self.delay(attempt, rng)


@dataclass(frozen=True)
class EngineSettings:
    connections: int = 8
    per_host_limit: int = 8
    min_segment: int = MIB
    buffer_size: int = MIB  # per connection; spec caps it at 4 MiB
    state_interval: float = 2.0  # seconds between crash-safe checkpoints
    progress_interval: float = 0.25
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    proxy: str | None = None  # manual HTTP(S) proxy URL
    use_system_proxy: bool = True  # environment/registry proxy when no manual proxy

    def effective_connections(self) -> int:
        return max(1, min(self.connections, self.per_host_limit, MAX_CONNECTIONS))
