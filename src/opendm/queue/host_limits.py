"""Connections per host across all running downloads (spec 6.1, default 8)."""

from collections import defaultdict
from urllib.parse import urlsplit


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class HostLimiter:
    def __init__(self, per_host: int = 8) -> None:
        self.per_host = per_host
        self._used: defaultdict[str, int] = defaultdict(int)

    def in_use(self, host: str) -> int:
        return self._used[host.lower()]

    def acquire(self, host: str, wanted: int) -> int:
        """Grant up to ``wanted`` connections; 0 means the host is full."""
        host = host.lower()
        granted = max(0, min(wanted, self.per_host - self._used[host]))
        self._used[host] += granted
        return granted

    def release(self, host: str, count: int) -> None:
        host = host.lower()
        self._used[host] = max(0, self._used[host] - count)
