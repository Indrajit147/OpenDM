"""Repositories: jobs (incl. secrets and history), queues, categories, settings."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from opendm.core.branding import PARTIAL_SUFFIX, STATE_SUFFIX
from opendm.core.models import (
    MAIN_QUEUE_ID,
    AfterAction,
    Category,
    DownloadRequest,
    Job,
    JobState,
    Queue,
)
from opendm.storage.db import Database
from opendm.storage.repositories import (
    CategoryRepository,
    JobRepository,
    QueueRepository,
    SettingsRepository,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


def request(name: str = "a.bin", **kwargs: object) -> DownloadRequest:
    return DownloadRequest(url=f"http://h/{name}", dest_dir=Path("D:/dl"), **kwargs)  # type: ignore[arg-type]


# --- jobs --------------------------------------------------------------------------------------


def test_add_get_round_trip(db: Database) -> None:
    jobs = JobRepository(db)
    job = Job(
        request(
            "a.bin", filename="a.bin", referrer="http://h/", user_agent="UA",
            checksum="md5:" + "0" * 32, speed_limit=1000, verify_tls=False,
            headers={"X-Test": "1"},
        ),
        size=100, connections=4, final_path=Path("D:/dl/a.bin"),
    )  # fmt: skip
    jobs.add(job)
    loaded = jobs.get(job.id)
    assert loaded == job


def test_positions_increase_per_queue(db: Database) -> None:
    jobs = JobRepository(db)
    queues = QueueRepository(db)
    other = queues.add(Queue("Night"))
    a, b = jobs.add(Job(request("a"))), jobs.add(Job(request("b")))
    c = jobs.add(Job(request("c"), queue_id=other.id))  # type: ignore[arg-type]
    assert (a.position, b.position, c.position) == (1, 2, 1)


def test_save_and_progress(db: Database) -> None:
    jobs = JobRepository(db)
    job = jobs.add(Job(request()))
    jobs.update_progress(job.id, downloaded=50, size=100)
    job = jobs.get(job.id)  # type: ignore[assignment]
    assert (job.downloaded, job.size) == (50, 100)
    job.state, job.message, job.error_kind = JobState.FAILED, "boom", "network"
    jobs.save(job)
    assert jobs.get(job.id) == job


@windows_only
def test_secrets_are_encrypted_at_rest(tmp_path: Path) -> None:
    path = tmp_path / "opendm.db"
    db = Database(path)
    jobs = JobRepository(db)
    req = request(
        cookies="session=TOPSECRET1",
        headers={"Authorization": "Bearer TOPSECRET2", "X-Ok": "visible"},
    )
    job = jobs.add(Job(req))
    db.close()
    raw = path.read_bytes() + (
        path.with_name(path.name + "-wal").read_bytes()
        if path.with_name(path.name + "-wal").exists()
        else b""
    )
    assert b"TOPSECRET" not in raw
    assert b"visible" in raw
    db = Database(path)
    loaded = JobRepository(db).get(job.id)
    assert loaded is not None
    assert loaded.request.cookies == "session=TOPSECRET1"
    assert loaded.request.headers == {"Authorization": "Bearer TOPSECRET2", "X-Ok": "visible"}
    db.close()


def test_secrets_dropped_when_unavailable(db: Database) -> None:
    jobs = JobRepository(db, store_secrets=False)
    job = jobs.add(Job(request(cookies="c=1", headers={"Cookie": "d=2", "X-Ok": "1"})))
    loaded = jobs.get(job.id)
    assert loaded is not None
    assert loaded.request.cookies is None
    assert loaded.request.headers == {"X-Ok": "1"}


def test_list_filters_and_search(db: Database) -> None:
    jobs = JobRepository(db)
    night = QueueRepository(db).add(Queue("Night"))
    a = jobs.add(Job(request("holiday.mp4"), category_id=1))
    b = jobs.add(Job(request("report.pdf"), category_id=3, state=JobState.PAUSED))
    c = jobs.add(Job(request("movie.mkv"), category_id=1, queue_id=night.id))  # type: ignore[arg-type]
    ids = lambda js: [j.id for j in js]  # noqa: E731
    assert ids(jobs.list()) == [a.id, b.id, c.id]
    assert ids(jobs.list(states={JobState.PAUSED})) == [b.id]
    assert ids(jobs.list(queue_id=night.id)) == [c.id]
    assert ids(jobs.list(category_id=1)) == [a.id, c.id]
    assert ids(jobs.list(search="REPORT")) == [b.id]
    assert ids(jobs.list(search="%")) == []  # LIKE wildcards are escaped
    assert ids(jobs.list(limit=1, offset=1)) == [b.id]


def test_history_newest_first(db: Database) -> None:
    jobs = JobRepository(db)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    old = jobs.add(Job(request("old.zip"), state=JobState.COMPLETED, completed_at=t0))
    new = jobs.add(
        Job(request("new.zip"), state=JobState.COMPLETED, completed_at=t0 + timedelta(1))
    )
    jobs.add(Job(request("running.zip"), state=JobState.DOWNLOADING))
    assert [j.id for j in jobs.history()] == [new.id, old.id]
    assert [j.id for j in jobs.history(search="old")] == [old.id]
    assert jobs.clear_history() == 2
    assert len(jobs.list()) == 1


def test_mark_interrupted(db: Database) -> None:
    jobs = JobRepository(db)
    running = jobs.add(Job(request("a"), state=JobState.DOWNLOADING))
    probing = jobs.add(Job(request("b"), state=JobState.PROBING))
    queued = jobs.add(Job(request("c")))
    assert jobs.mark_interrupted() == 2
    for job_id in (running.id, probing.id):
        job = jobs.get(job_id)
        assert job is not None and job.state is JobState.PAUSED and job.message == "interrupted"
    assert jobs.get(queued.id).state is JobState.QUEUED  # type: ignore[union-attr]


def test_delete_entry_keeps_file_unless_asked(db: Database, tmp_path: Path) -> None:
    jobs = JobRepository(db)
    target = tmp_path / "a.bin"
    target.write_text("x")
    job = jobs.add(Job(request(), final_path=target, state=JobState.COMPLETED))
    assert jobs.delete(job.id)
    assert target.exists() and jobs.get(job.id) is None
    job = jobs.add(Job(request(), final_path=target, state=JobState.COMPLETED))
    assert jobs.delete(job.id, delete_file=True)
    assert not target.exists()
    assert not jobs.delete("missing")


def test_delete_unfinished_removes_partial_files(db: Database, tmp_path: Path) -> None:
    jobs = JobRepository(db)
    target = tmp_path / "a.bin"
    part = tmp_path / ("a.bin" + PARTIAL_SUFFIX)
    state = tmp_path / ("a.bin" + STATE_SUFFIX)
    part.write_text("p")
    state.write_text("s")
    job = jobs.add(Job(request(), final_path=target, state=JobState.PAUSED))
    jobs.delete(job.id, delete_file=True)
    assert not part.exists() and not state.exists()


def test_redownload_copies_the_request(db: Database) -> None:
    jobs = JobRepository(db)
    done = jobs.add(
        Job(request("a.bin", referrer="r"), state=JobState.COMPLETED, sha256="x", downloaded=9)
    )
    again = jobs.redownload(done.id)
    assert again.id != done.id
    assert again.request == done.request
    assert (again.state, again.downloaded, again.sha256, again.final_path) == (
        JobState.QUEUED, 0, None, None,
    )  # fmt: skip
    assert jobs.get(again.id) == again


# --- queues ------------------------------------------------------------------------------------


def test_queue_crud(db: Database) -> None:
    queues = QueueRepository(db)
    assert [q.name for q in queues.list()] == ["Main"]
    night = queues.add(
        Queue("Night", max_concurrent=2, start_time="01:00", stop_time="06:00", days=0b11111,
              after_action=AfterAction.SHUTDOWN)
    )  # fmt: skip
    assert night.id is not None and night.position == 1
    assert queues.get(night.id) == night
    night.max_concurrent = 5
    queues.save(night)
    assert queues.get(night.id).max_concurrent == 5  # type: ignore[union-attr]


def test_deleting_a_queue_moves_jobs_to_main(db: Database) -> None:
    queues, jobs = QueueRepository(db), JobRepository(db)
    night = queues.add(Queue("Night"))
    job = jobs.add(Job(request(), queue_id=night.id))  # type: ignore[arg-type]
    queues.delete(night.id)  # type: ignore[arg-type]
    assert jobs.get(job.id).queue_id == MAIN_QUEUE_ID  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        queues.delete(MAIN_QUEUE_ID)


def test_queue_validation(db: Database) -> None:
    queues = QueueRepository(db)
    with pytest.raises(ValueError):
        queues.add(Queue("Bad", start_time="25:00"))
    with pytest.raises(ValueError):
        queues.add(Queue("Bad", max_concurrent=0))
    with pytest.raises(ValueError):
        queues.add(Queue("Main"))  # duplicate name


# --- categories and settings -----------------------------------------------------------------


def test_category_crud(db: Database) -> None:
    categories = CategoryRepository(db)
    listed = categories.list()
    assert [c.name for c in listed][:2] == ["Video", "Audio"]
    assert listed[0].extensions[:2] == ("mp4", "mkv")
    assert categories.fallback().name == "Other"
    books = categories.add(Category("Books", ("epub", ".MOBI"), folder="E:/Books"))
    assert books.extensions == ("epub", "mobi")  # normalized
    books.folder = "Books"
    categories.save(books)
    assert categories.get(books.id).folder == "Books"  # type: ignore[arg-type, union-attr]
    categories.delete(books.id)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        categories.delete(categories.fallback().id)  # type: ignore[arg-type]


def test_settings(db: Database) -> None:
    settings = SettingsRepository(db)
    assert settings.get("download_dir", "D:/Downloads") == "D:/Downloads"
    settings.set("download_dir", "E:/dl")
    settings.set("limits", {"per_host": 8, "global": None})
    assert settings.get("download_dir") == "E:/dl"
    assert settings.get("limits") == {"per_host": 8, "global": None}
