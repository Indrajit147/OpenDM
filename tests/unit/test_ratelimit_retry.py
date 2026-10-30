"""Token bucket, retry policy, Retry-After parsing, checksums and settings."""

import hashlib
from email.utils import formatdate
from pathlib import Path

import pytest

from opendm.core.checksum import file_digest, parse_checksum
from opendm.core.settings import EngineSettings, RetryPolicy
from opendm.engine.http.ratelimit import TokenBucket, acquire_all
from opendm.engine.http.retry import parse_retry_after


class FakeTime:
    """A clock plus an async sleep that advances it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept = 0.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds


# --- token bucket ---------------------------------------------------------------


async def test_unlimited_bucket_never_sleeps() -> None:
    t = FakeTime()
    bucket = TokenBucket(None, clock=t.clock, sleep=t.sleep)
    await bucket.acquire(10**9)
    assert t.slept == 0


async def test_bucket_enforces_rate() -> None:
    t = FakeTime()
    bucket = TokenBucket(1000, clock=t.clock, sleep=t.sleep)
    for _ in range(50):
        await bucket.acquire(100)  # 5000 bytes at 1000 B/s
    assert t.now - 1000.0 == pytest.approx(5.0, rel=0.01)


async def test_bucket_does_not_bank_idle_time_beyond_burst() -> None:
    t = FakeTime()
    bucket = TokenBucket(1000, clock=t.clock, sleep=t.sleep)
    t.now += 60  # idle for a minute
    await bucket.acquire(1000)
    # only the burst (0.1 s worth) was banked, so most of the 1000 bytes still cost time
    assert t.slept == pytest.approx(0.9, rel=0.01)


async def test_bucket_rate_can_change() -> None:
    t = FakeTime()
    bucket = TokenBucket(1000, clock=t.clock, sleep=t.sleep)
    bucket.rate = None
    await bucket.acquire(10**6)
    assert t.slept == 0
    bucket.rate = 2000
    await bucket.acquire(2000)
    assert t.slept == pytest.approx(1.0, rel=0.01)


async def test_acquire_all_respects_the_slowest() -> None:
    t = FakeTime()
    fast = TokenBucket(10_000, clock=t.clock, sleep=t.sleep)
    slow = TokenBucket(1000, clock=t.clock, sleep=t.sleep)
    for _ in range(10):
        await acquire_all([fast, None, slow], 100)
    assert t.now - 1000.0 == pytest.approx(1.0, rel=0.05)


def test_bucket_rejects_bad_rate() -> None:
    with pytest.raises(ValueError):
        TokenBucket(-5)


# --- retry ------------------------------------------------------------------------


def test_backoff_grows_and_caps() -> None:
    policy = RetryPolicy(base_delay=1, factor=2, max_delay=30)
    top = lambda: 1.0  # noqa: E731  (worst-case jitter)
    assert [policy.delay(a, top) for a in range(7)] == [1, 2, 4, 8, 16, 30, 30]
    assert policy.delay(3, lambda: 0.5) == 4.0


def test_retry_after_wins_but_is_capped() -> None:
    policy = RetryPolicy(max_retry_after=60)
    assert policy.wait_for(0, 5.0) == 5.0
    assert policy.wait_for(0, 999.0) == 60.0
    assert policy.wait_for(0, -3.0) == 0.0
    assert policy.wait_for(2, None, lambda: 1.0) == 4.0


def test_parse_retry_after() -> None:
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after(" 0 ") == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    future = formatdate(1_000_030, usegmt=True)
    assert parse_retry_after(future, now=1_000_000) == pytest.approx(30.0)
    past = formatdate(999_000, usegmt=True)
    assert parse_retry_after(past, now=1_000_000) == 0.0


def test_effective_connections() -> None:
    assert EngineSettings().effective_connections() == 8
    assert EngineSettings(connections=16, per_host_limit=4).effective_connections() == 4
    assert EngineSettings(connections=99, per_host_limit=99).effective_connections() == 32
    assert EngineSettings(connections=0).effective_connections() == 1


# --- checksums ---------------------------------------------------------------------


def test_parse_checksum() -> None:
    sha = "A" * 64
    assert parse_checksum(f"sha256:{sha}") == ("sha256", sha.lower())
    assert parse_checksum(sha) == ("sha256", sha.lower())  # inferred from length
    assert parse_checksum("b" * 40) == ("sha1", "b" * 40)
    assert parse_checksum("MD5:" + "c" * 32) == ("md5", "c" * 32)


@pytest.mark.parametrize("bad", ["sha256:abc", "crc32:1234abcd", "z" * 64, "", "sha1:" + "a" * 64])
def test_parse_checksum_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_checksum(bad)


def test_file_digest(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello" * 1000)
    assert file_digest(path, "sha256") == hashlib.sha256(b"hello" * 1000).hexdigest()
    assert file_digest(path, "md5") == hashlib.md5(b"hello" * 1000).hexdigest()
