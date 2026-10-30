"""EngineThread: the asyncio engine on its own thread (no Qt)."""

import threading
import time
from pathlib import Path

import pytest

from opendm.core.bridge import EngineThread, coalesce
from opendm.core.events import Event, JobSnapshot, Progress, StateChanged
from opendm.core.models import AfterAction, DownloadRequest, JobState, Queue
from tests.server.app import FaultServer, content_sha256


def progress(job_id: str, n: int) -> Progress:
    return Progress(job_id, n, 100, 0.0, None)


def test_coalesce_keeps_latest_progress_per_job_in_order() -> None:
    s = StateChanged("a", JobState.DOWNLOADING)
    events: list[Event] = [
        progress("a", 1),
        progress("b", 1),
        s,
        progress("a", 2),
        progress("b", 5),
    ]
    assert coalesce(events) == [s, progress("a", 2), progress("b", 5)]
    assert coalesce([]) == []


def wait_for(engine: EngineThread, predicate, timeout: float = 20) -> list[Event]:
    seen: list[Event] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seen += engine.drain()
        if predicate(seen):
            return seen
        time.sleep(0.02)
    pytest.fail("condition not reached")


def test_engine_thread_runs_downloads(server: FaultServer, tmp_path: Path) -> None:
    engine = EngineThread(tmp_path / "opendm.db")
    engine.start()
    try:
        assert engine.thread is not None and engine.thread is not threading.current_thread()
        url = server.url("/file/e.bin?size=300000")
        job = engine.call(
            lambda m: m.add(DownloadRequest(url=url, dest_dir=tmp_path / "dl"))
        ).result(10)

        def completed(seen: list[Event]) -> bool:
            return any(
                isinstance(e, JobSnapshot) and e.job and e.job.state is JobState.COMPLETED
                for e in seen
            )

        events = wait_for(engine, completed)
        snapshot = next(e for e in reversed(events) if isinstance(e, JobSnapshot))
        assert snapshot.job_id == job.id
        assert snapshot.job is not None and snapshot.job.sha256 == content_sha256(300000, 1)
        # plain (non-async) calls work too and run on the engine thread
        names = engine.call(lambda m: (threading.current_thread().name, len(m.jobs.list())))
        assert names.result(5) == ("opendm-engine", 1)
    finally:
        engine.stop()
    assert not engine.thread.is_alive()  # type: ignore[union-attr]
    with pytest.raises(RuntimeError):
        engine.call(lambda m: None)


def test_removed_job_snapshot(server: FaultServer, tmp_path: Path) -> None:
    engine = EngineThread(tmp_path / "opendm.db")
    engine.start()
    try:
        url = server.url("/file/r.bin?size=10")
        job = engine.call(
            lambda m: m.add(DownloadRequest(url=url, dest_dir=tmp_path), start=False)
        ).result(5)
        engine.call(lambda m: m.remove(job.id)).result(5)
        wait_for(engine, lambda seen: JobSnapshot(job.id, None) in seen)
    finally:
        engine.stop()


def test_power_requests_become_events(tmp_path: Path) -> None:
    engine = EngineThread(tmp_path / "opendm.db")
    engine.start()
    try:
        engine.call(
            lambda m: m._power.perform(AfterAction.SLEEP, Queue("Night"))  # type: ignore[attr-defined]
        ).result(5)
        events = wait_for(engine, lambda seen: bool(seen))
        assert events[-1].action is AfterAction.SLEEP  # type: ignore[union-attr]
        assert events[-1].queue_name == "Night"  # type: ignore[union-attr]
    finally:
        engine.stop()


def test_startup_failure_is_reported(tmp_path: Path) -> None:
    folder = tmp_path / "is-a-folder.db"
    folder.mkdir()
    engine = EngineThread(folder)
    with pytest.raises(Exception, match="unable to open"):
        engine.start()
    engine.stop()  # harmless after a failed start


def test_stop_pauses_running_downloads(server: FaultServer, tmp_path: Path) -> None:
    engine = EngineThread(tmp_path / "opendm.db")
    engine.start()
    url = server.url("/file/s.bin?size=2M&rate=256K")
    job = engine.call(lambda m: m.add(DownloadRequest(url=url, dest_dir=tmp_path))).result(5)
    wait_for(engine, lambda seen: any(isinstance(e, Progress) for e in seen))
    engine.stop()
    again = EngineThread(tmp_path / "opendm.db")
    again.start()
    try:
        stored = again.call(lambda m: m.jobs.get(job.id)).result(5)
        assert stored.state is JobState.PAUSED and stored.message == "interrupted"
    finally:
        again.stop()
