"""DownloadManager running media (yt-dlp) jobs, with the fake yt-dlp."""

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from opendm.core.events import Event, Progress, ToolsMissing
from opendm.core.models import DownloadRequest, Job, JobState
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import ToolPaths
from opendm.queue.scheduler import DownloadManager
from opendm.storage.db import Database

FAKE = Path(__file__).resolve().parents[1] / "fake_tools" / "fake_ytdlp.py"


@pytest.fixture
async def manager(tmp_path: Path) -> AsyncIterator[tuple[DownloadManager, list[Event]]]:
    events: list[Event] = []
    db = Database(tmp_path / "opendm.db")
    m = DownloadManager(db, sink=events.append, temp_dir=tmp_path / "tmp")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"")
    m.set_tools(ToolPaths(ffmpeg=ffmpeg, command=(sys.executable, str(FAKE))))
    await m.open()
    yield m, events
    await m.close()
    db.close()


async def wait_for(predicate, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.02)


def job(m: DownloadManager, job_id: str) -> Job:
    found = m.jobs.get(job_id)
    assert found is not None
    return found


async def test_analyze_and_download_media(manager, tmp_path: Path) -> None:
    m, _ = manager
    request = DownloadRequest("http://fake/ok", tmp_path / "dl")
    info = await m.analyze_media(request)
    assert info.title == "Fake Clip" and info.heights == [1080, 720]
    added = await m.add_media(request, MediaOptions(quality="720"))
    assert added.kind == "media"
    await m.wait_idle()
    done = job(m, added.id)
    assert done.state is JobState.COMPLETED
    assert done.final_path == tmp_path / "dl" / "Fake Clip [abc].mp4"
    assert done.size == 1400 and done.sha256
    assert done.media_options == MediaOptions(quality="720").to_dict()


async def test_media_job_survives_reload(manager, tmp_path: Path) -> None:
    m, _ = manager
    added = await m.add_media(
        DownloadRequest("http://fake/ok", tmp_path), MediaOptions(), start=False
    )
    stored = job(m, added.id)
    assert stored.kind == "media"
    assert MediaOptions.from_dict(stored.media_options or {}) == MediaOptions()


async def test_media_pause_and_resume(manager, tmp_path: Path) -> None:
    m, events = manager
    added = await m.add_media(DownloadRequest("http://fake/slow", tmp_path), MediaOptions())

    def progressed() -> bool:
        return any(isinstance(e, Progress) and e.job_id == added.id and e.downloaded > 200
                   for e in events)  # fmt: skip

    await wait_for(progressed)
    await m.pause(added.id)
    assert job(m, added.id).state is JobState.PAUSED
    await m.start(added.id)
    await m.wait_idle()
    assert job(m, added.id).state is JobState.COMPLETED


async def test_protected_media_fails_with_clear_message(manager, tmp_path: Path) -> None:
    m, _ = manager
    added = await m.add_media(DownloadRequest("http://fake/drm", tmp_path), MediaOptions())
    await m.wait_idle()
    failed = job(m, added.id)
    assert failed.state is JobState.FAILED
    assert failed.error_kind == "protected" and "not supported" in (failed.error_message or "")


async def test_missing_tools_make_media_jobs_wait(tmp_path: Path) -> None:
    events: list[Event] = []
    db = Database(":memory:")
    m = DownloadManager(db, sink=events.append, temp_dir=tmp_path / "tmp")
    await m.open()
    first = await m.add_media(DownloadRequest("http://fake/ok", tmp_path / "a"), MediaOptions())
    second = await m.add_media(DownloadRequest("http://fake/ok", tmp_path / "b"), MediaOptions())
    await m.wait_idle()
    for added in (first, second):
        waiting = job(m, added.id)
        assert waiting.state is JobState.QUEUED and waiting.error_kind is None
        assert "waiting for yt-dlp" in waiting.message
    missing = [e for e in events if isinstance(e, ToolsMissing)]
    assert len(missing) == 1 and set(missing[0].names) == {"yt-dlp", "ffmpeg"}  # asked once

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"")
    m.set_tools(ToolPaths(ffmpeg=ffmpeg, command=(sys.executable, str(FAKE))))  # tools are back
    await wait_for(lambda: all(job(m, j.id).state is JobState.COMPLETED for j in (first, second)))
    await m.close()
    db.close()


async def test_http_jobs_do_not_wait_for_tools(tmp_path: Path, server) -> None:
    db = Database(":memory:")
    m = DownloadManager(db, temp_dir=tmp_path / "tmp")
    await m.open()
    added = await m.add(DownloadRequest(server.url("/file/x.bin?size=10K"), tmp_path))
    await wait_for(lambda: job(m, added.id).state is JobState.COMPLETED)
    await m.close()
    db.close()


async def test_tools_vanishing_mid_queue_make_the_job_wait(manager, tmp_path: Path) -> None:
    m, events = manager
    m.set_tools(ToolPaths(ytdlp=tmp_path / "gone" / "yt-dlp.exe", ffmpeg=tmp_path / "ffmpeg.exe"))
    added = await m.add_media(DownloadRequest("http://fake/ok", tmp_path), MediaOptions())
    await m.wait_idle()
    waiting = job(m, added.id)
    assert waiting.state is JobState.QUEUED and "waiting for yt-dlp" in waiting.message
    assert [e.names for e in events if isinstance(e, ToolsMissing)] == [("yt-dlp",)]


async def test_a_vanished_executable_is_reported_as_missing(tmp_path: Path) -> None:
    from opendm.core.errors import DownloadError, ErrorKind
    from opendm.engine.media.download import MediaDownload

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"")
    gone = tmp_path / "yt-dlp.exe"  # passed the check, then deleted before it started
    tools = ToolPaths(ffmpeg=ffmpeg, command=(str(gone),))
    download = MediaDownload(
        DownloadRequest("http://fake/ok", tmp_path), MediaOptions(), tools=tools,
        temp_dir=tmp_path / "tmp",
    )  # fmt: skip
    with pytest.raises(DownloadError) as exc:
        await download.run()
    assert exc.value.kind is ErrorKind.TOOL_MISSING
    assert exc.value.message == "yt-dlp is not installed"


async def test_redownload_keeps_media_options(manager, tmp_path: Path) -> None:
    m, _ = manager
    added = await m.add_media(DownloadRequest("http://fake/ok", tmp_path),
                              MediaOptions(quality="audio-m4a"))  # fmt: skip
    await m.wait_idle()
    again = await m.redownload(added.id, start=False)
    assert again.media_options == {**MediaOptions(quality="audio-m4a").to_dict()}


async def test_tools_that_look_installed_but_do_not_start_fail_once(tmp_path: Path) -> None:
    db = Database(":memory:")
    m = DownloadManager(db, temp_dir=tmp_path / "tmp")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"")
    m.set_tools(ToolPaths(ffmpeg=ffmpeg, command=(str(tmp_path / "no-such.exe"),)))
    await m.open()
    added = await m.add_media(DownloadRequest("http://fake/ok", tmp_path), MediaOptions())
    await wait_for(lambda: job(m, added.id).state is JobState.FAILED)
    assert job(m, added.id).error_kind == "tool_missing"
    await m.close()
    db.close()


async def test_jobs_not_due_to_run_do_not_ask_for_tools(tmp_path: Path) -> None:
    events: list[Event] = []
    db = Database(":memory:")
    m = DownloadManager(db, sink=events.append, temp_dir=tmp_path / "tmp")
    await m.open()
    added = await m.add_media(
        DownloadRequest("http://fake/ok", tmp_path), MediaOptions(), start=False
    )
    await m.wait_idle()
    assert job(m, added.id).message == ""
    assert not [e for e in events if isinstance(e, ToolsMissing)]
    await m.close()
    db.close()
