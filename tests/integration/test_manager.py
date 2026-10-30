"""DownloadManager: persistence, queues, host limits and schedules (milestone M3)."""

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path

import pytest

from opendm.core.events import Event, JobChanged, Progress, QueueFinished, StateChanged
from opendm.core.models import AfterAction, DownloadRequest, Job, JobState, Queue
from opendm.core.settings import EngineSettings, RetryPolicy
from opendm.queue.host_limits import HostLimiter
from opendm.queue.scheduler import DownloadManager
from opendm.storage.db import Database
from tests.server.app import COOKIE_NAME, COOKIE_VALUE, FaultServer, content_seed, content_sha256

KIB, MIB = 1024, 1024 * 1024
TIMEOUT = 30

ENGINE = EngineSettings(
    connections=4,
    min_segment=64 * KIB,
    buffer_size=64 * KIB,
    state_interval=0.1,
    progress_interval=0.01,
    retry=RetryPolicy(max_retries=3, base_delay=0.01, max_delay=0.05, max_retry_after=0.1),
)


class FakePower:
    def __init__(self) -> None:
        self.calls: list[tuple[AfterAction, str]] = []

    async def perform(self, action: AfterAction, queue: Queue) -> None:
        self.calls.append((action, queue.name))


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Harness:
    def __init__(self, db: Database, **kwargs: object) -> None:
        self.events: list[Event] = []
        self.stamps: list[float] = []  # perf_counter() of each event
        self.power = FakePower()
        options: dict[str, object] = {"settings": ENGINE, "power": self.power, "per_host": 64}
        options.update(kwargs)
        self.manager = DownloadManager(db, sink=self._record, **options)  # type: ignore[arg-type]

    def _record(self, event: Event) -> None:
        self.events.append(event)
        self.stamps.append(time.perf_counter())

    def job(self, job_id: str) -> Job:
        job = self.manager.jobs.get(job_id)
        assert job is not None
        return job

    async def wait_for(self, predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + TIMEOUT
        while not predicate():
            if time.monotonic() > deadline:
                pytest.fail("timed out waiting for a condition")
            await asyncio.sleep(0.01)

    def downloaded(self, job_id: str) -> int:
        progress = [e for e in self.events if isinstance(e, Progress) and e.job_id == job_id]
        return progress[-1].downloaded if progress else 0


@pytest.fixture
async def h(tmp_path: Path) -> AsyncIterator[Harness]:
    db = Database(tmp_path / "opendm.db")
    harness = Harness(db)
    await harness.manager.open()
    yield harness
    await harness.manager.close()
    db.close()


def req(server: FaultServer, path: str, dest: Path, **kwargs: object) -> DownloadRequest:
    return DownloadRequest(url=server.url(path), dest_dir=dest, **kwargs)  # type: ignore[arg-type]


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- host limiter (unit) -------------------------------------------------------------------------


def test_host_limiter() -> None:
    hosts = HostLimiter(8)
    assert hosts.acquire("a.com", 6) == 6
    assert hosts.acquire("a.com", 6) == 2
    assert hosts.acquire("a.com", 1) == 0
    assert hosts.acquire("b.com", 8) == 8  # other hosts are independent
    hosts.release("a.com", 6)
    assert hosts.in_use("a.com") == 2
    assert hosts.acquire("A.COM", 10) == 6  # host names are case-insensitive
    hosts.release("a.com", 100)
    assert hosts.in_use("a.com") == 0


# --- basic flow ---------------------------------------------------------------------------------


async def test_add_and_complete(h: Harness, server: FaultServer, tmp_path: Path) -> None:
    job = await h.manager.add(req(server, "/file/a.zip?size=1M", tmp_path / "dl"))
    assert job.category_id == h.manager.categories.list()[3].id  # Compressed
    await h.manager.wait_idle()
    done = h.job(job.id)
    assert done.state is JobState.COMPLETED
    assert done.final_path == tmp_path / "dl" / "a.zip"
    assert done.sha256 == content_sha256(MIB, 1) == sha_of(done.final_path)
    assert done.downloaded == done.size == MIB
    assert done.started_at and done.completed_at
    assert any(isinstance(e, JobChanged) and e.job_id == job.id for e in h.events)
    assert [j.id for j in h.manager.jobs.history()] == [job.id]


async def test_add_without_start_waits_in_queue(h: Harness, server, tmp_path: Path) -> None:
    job = await h.manager.add(req(server, "/file/a.bin?size=10", tmp_path), start=False)
    await asyncio.sleep(0.2)
    assert h.job(job.id).state is JobState.QUEUED
    await h.manager.start(job.id)
    await h.manager.wait_idle()
    assert h.job(job.id).state is JobState.COMPLETED


async def test_failure_is_recorded(h: Harness, server: FaultServer, tmp_path: Path) -> None:
    job = await h.manager.add(req(server, "/status/404", tmp_path))
    await h.manager.wait_idle()
    failed = h.job(job.id)
    assert failed.state is JobState.FAILED
    assert failed.error_kind == "not_found"


async def test_pause_resume_and_remove(h: Harness, server: FaultServer, tmp_path: Path) -> None:
    job = await h.manager.add(req(server, "/file/p.bin?size=2M&rate=512K", tmp_path))
    await h.wait_for(lambda: h.downloaded(job.id) > 200_000)
    await h.manager.pause(job.id)
    paused = h.job(job.id)
    assert paused.state is JobState.PAUSED
    assert paused.downloaded > 0 and paused.final_path is not None
    await h.manager.start(job.id)
    await h.wait_for(lambda: h.job(job.id).state is JobState.DOWNLOADING)
    await h.manager.remove(job.id, delete_file=True)
    assert h.manager.jobs.get(job.id) is None
    assert list(tmp_path.glob("p.bin*")) == []


async def test_global_speed_limit(h: Harness, server: FaultServer, tmp_path: Path) -> None:
    h.manager.set_global_speed_limit(MIB)
    for name in ("a", "b"):
        await h.manager.add(req(server, f"/file/{name}.bin?size=1M", tmp_path))
    await h.manager.wait_idle()
    # Transfer rate between the first and last progress report (probes and the final
    # SHA-256 pass are not throttled transfer time).
    stamps = [t for t, e in zip(h.stamps, h.events, strict=True) if isinstance(e, Progress)]
    rate = 2 * MIB / (stamps[-1] - stamps[0])
    assert 0.9 * MIB <= rate <= 1.1 * MIB  # 2 MiB shared at 1 MiB/s


async def test_redownload(h: Harness, server: FaultServer, tmp_path: Path) -> None:
    job = await h.manager.add(req(server, "/file/r.bin?size=1000", tmp_path))
    await h.manager.wait_idle()
    again = await h.manager.redownload(job.id)
    await h.manager.wait_idle()
    assert h.job(again.id).final_path == tmp_path / "r (1).bin"


# --- persistence --------------------------------------------------------------------------------


async def test_jobs_persist_across_restarts(server: FaultServer, tmp_path: Path) -> None:
    path = "/protected/keep.bin?size=2M&rate=512K"
    cookie = f"{COOKIE_NAME}={COOKIE_VALUE}"
    db = Database(tmp_path / "opendm.db")
    first = Harness(db)
    await first.manager.open()
    job = await first.manager.add(req(server, path, tmp_path / "dl", cookies=cookie))
    queued = await first.manager.add(req(server, "/file/later.bin?size=10", tmp_path), start=False)
    await first.wait_for(lambda: first.downloaded(job.id) > 300_000)
    await first.manager.close()  # app exit
    db.close()

    db = Database(tmp_path / "opendm.db")
    second = Harness(db)
    assert await second.manager.open() == 0  # nothing was left running
    reloaded = second.job(job.id)
    assert reloaded.state is JobState.PAUSED and reloaded.message == "interrupted"
    assert reloaded.downloaded > 0
    assert reloaded.request.cookies == cookie  # decrypted from the database
    assert second.job(queued.id).state is JobState.QUEUED
    await asyncio.sleep(0.2)
    assert second.job(job.id).state is JobState.PAUSED  # decision M3-2: no auto-start

    await second.manager.start(job.id)
    await second.manager.wait_idle()
    done = second.job(job.id)
    assert done.state is JobState.COMPLETED
    assert done.sha256 == content_sha256(2 * MIB, 1)
    assert server.stats(path)["bytes_sent"] <= 2 * MIB + 512 * KIB
    await second.manager.close()
    db.close()


async def test_crash_leaves_job_interrupted(server: FaultServer, tmp_path: Path) -> None:
    db = Database(tmp_path / "opendm.db")
    first = Harness(db)
    await first.manager.open()
    job = await first.manager.add(req(server, "/file/c.bin?size=2M&rate=512K", tmp_path))
    await first.wait_for(lambda: first.downloaded(job.id) > 300_000)
    await first.manager.pause(job.id)
    # The process "dies" before it can record the pause: the row still says DOWNLOADING.
    db.execute("UPDATE jobs SET state = 'downloading' WHERE id = ?", (job.id,))
    db.close()

    db = Database(tmp_path / "opendm.db")
    second = Harness(db)
    assert await second.manager.open() == 1
    assert second.job(job.id).state is JobState.PAUSED
    assert second.job(job.id).message == "interrupted"
    await second.manager.start(job.id)
    await second.manager.wait_idle()
    assert second.job(job.id).sha256 == content_sha256(2 * MIB, 1)
    await second.manager.close()
    db.close()


# --- queues and host limits ---------------------------------------------------------------------


def concurrency(events: list[Event]) -> tuple[int, list[str]]:
    """Peak number of jobs between PROBING and a final state, and the start order."""
    running: set[str] = set()
    peak, order = 0, []
    final = {JobState.COMPLETED, JobState.FAILED, JobState.PAUSED, JobState.CANCELLED}
    for e in events:
        if isinstance(e, StateChanged) and e.state is JobState.PROBING and e.job_id not in running:
            running.add(e.job_id)
            order.append(e.job_id)
            peak = max(peak, len(running))
        elif isinstance(e, StateChanged) and e.state in final:
            running.discard(e.job_id)
    return peak, order


async def test_queue_concurrency_is_respected(h: Harness, server, tmp_path: Path) -> None:
    queue = h.manager.queues.add(Queue("Two", max_concurrent=2))
    jobs = []
    for i in range(5):
        request = req(server, f"/file/q{i}.bin?size=300K&rate=1M", tmp_path)
        jobs.append(await h.manager.add(request, queue_id=queue.id, start=False))  # type: ignore[arg-type]
    await h.manager.start_queue(queue.id)  # type: ignore[arg-type]
    await h.manager.wait_idle()
    peak, order = concurrency(h.events)
    assert peak == 2
    assert order == [j.id for j in jobs]
    assert all(h.job(j.id).state is JobState.COMPLETED for j in jobs)
    finished = [e for e in h.events if isinstance(e, QueueFinished)]
    assert [(e.name, e.action) for e in finished] == [("Two", AfterAction.NONE)]


async def test_per_host_limit_shares_connections(server: FaultServer, tmp_path: Path) -> None:
    db = Database(":memory:")
    h = Harness(db, per_host=6)
    await h.manager.open()
    a = await h.manager.add(req(server, "/file/h1.bin?size=2M&rate=512K", tmp_path))
    b = await h.manager.add(req(server, "/file/h2.bin?size=2M&rate=512K", tmp_path))
    await h.manager.wait_idle()

    def peak_connections(job_id: str) -> int:
        return max(
            e.connections for e in h.events if isinstance(e, Progress) and e.job_id == job_id
        )

    assert peak_connections(a.id) == 4  # the engine's own limit
    assert peak_connections(b.id) == 2  # what was left of the host's 6
    await h.manager.close()


async def test_host_full_makes_jobs_wait(server: FaultServer, tmp_path: Path) -> None:
    db = Database(":memory:")
    h = Harness(db, per_host=4)
    await h.manager.open()
    a = await h.manager.add(req(server, "/file/w1.bin?size=1M&rate=1M", tmp_path))
    b = await h.manager.add(req(server, "/file/w2.bin?size=1M&rate=1M", tmp_path))
    await h.manager.wait_idle()
    _, order = concurrency(h.events)
    assert order == [a.id, b.id]
    peak, _ = concurrency(h.events)
    assert peak == 1
    await h.manager.close()


# --- schedules -----------------------------------------------------------------------------------


async def test_schedule_start_stop_and_after_action(server: FaultServer, tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 2, 0, 59))  # Monday
    db = Database(":memory:")
    h = Harness(db, now=clock)
    await h.manager.open()
    night = h.manager.queues.add(
        Queue("Night", start_time="01:00", stop_time="02:00", after_action=AfterAction.SHUTDOWN)
    )
    job = await h.manager.add(
        req(server, "/file/n.bin?size=2M&rate=512K", tmp_path), queue_id=night.id, start=False
    )
    await h.manager.tick()
    await asyncio.sleep(0.1)
    assert h.job(job.id).state is JobState.QUEUED  # before the window

    clock.now = clock.now.replace(hour=1, minute=0)
    await h.manager.tick()
    await h.wait_for(lambda: h.downloaded(job.id) > 100_000)

    clock.now = clock.now.replace(hour=2, minute=0)
    await h.manager.tick()  # stop time: back in the queue, not "paused by user"
    stopped = h.job(job.id)
    assert stopped.state is JobState.QUEUED and "schedule" in stopped.message
    assert h.power.calls == []

    clock.now = clock.now.replace(day=3, hour=1, minute=0)  # Tuesday's window
    await h.manager.tick()
    await h.manager.wait_idle()
    assert h.job(job.id).state is JobState.COMPLETED
    assert h.job(job.id).sha256 == content_sha256(2 * MIB, 1)
    await asyncio.sleep(0.05)
    assert h.power.calls == [(AfterAction.SHUTDOWN, "Night")]
    await h.manager.close()


async def test_manual_stop_does_not_trigger_after_action(server, tmp_path: Path) -> None:
    db = Database(":memory:")
    h = Harness(db)
    await h.manager.open()
    q = h.manager.queues.add(Queue("Q", after_action=AfterAction.SLEEP))
    await h.manager.add(
        req(server, "/file/s.bin?size=2M&rate=256K", tmp_path), queue_id=q.id, start=False
    )
    await h.manager.start_queue(q.id)  # type: ignore[arg-type]
    await asyncio.sleep(0.3)
    await h.manager.stop_queue(q.id)  # type: ignore[arg-type]
    await h.manager.wait_idle()
    assert h.power.calls == []
    assert not any(isinstance(e, QueueFinished) for e in h.events)
    await h.manager.close()


async def test_empty_scheduled_queue_does_nothing(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 2, 1, 0))
    db = Database(":memory:")
    h = Harness(db, now=clock)
    await h.manager.open()
    h.manager.queues.add(
        Queue("Empty", start_time="01:00", stop_time="02:00", after_action=AfterAction.SHUTDOWN)
    )
    await h.manager.tick()
    await h.manager.wait_idle()
    assert h.power.calls == []  # never shut the PC down for a queue that ran nothing
    await h.manager.close()


# --- links ----------------------------------------------------------------------------------------


async def test_refresh_expired_link(h: Harness, server: FaultServer, tmp_path: Path) -> None:
    job = await h.manager.add(
        req(server, "/file/x.bin?size=1M&rate=256K&expire_after=0.3", tmp_path)
    )
    await h.wait_for(lambda: h.downloaded(job.id) > 100_000)
    await h.manager.pause(job.id)
    await asyncio.sleep(0.35)
    await h.manager.start(job.id)
    await h.manager.wait_idle()
    assert h.job(job.id).error_kind == "link_expired"
    await h.manager.refresh_link(job.id, server.url("/file/fresh?size=1M"))
    await h.manager.start(job.id)
    await h.manager.wait_idle()
    done = h.job(job.id)
    assert done.state is JobState.COMPLETED and done.final_path == tmp_path / "x.bin"
    assert done.sha256 == content_sha256(MIB, 1)


async def test_restart_after_validator_change(h: Harness, server, tmp_path: Path) -> None:
    job = await h.manager.add(req(server, "/file/v.bin?size=1M&etag_after=1", tmp_path))
    await h.manager.wait_idle()
    assert h.job(job.id).error_kind == "validator_changed"
    await h.manager.restart(job.id)
    await h.manager.wait_idle()
    assert h.job(job.id).sha256 == content_sha256(MIB, content_seed(1, version=1))
