"""Single-connection downloads against the local test server."""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from opendm.core.branding import PARTIAL_SUFFIX
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.events import Event, Failed, Finished, Progress, StateChanged
from opendm.core.models import DownloadRequest, JobState
from opendm.engine.http.single import SingleStreamDownload
from tests.server.app import COOKIE_NAME, COOKIE_VALUE, FaultServer, content_seed, content_sha256

SIZE = 300_000
UTF8_NAME = "রিপোর্ট € file.pdf"


def make(
    server: FaultServer, path: str, dest: Path, **kwargs: object
) -> tuple[SingleStreamDownload, list[Event]]:
    events: list[Event] = []
    request = DownloadRequest(url=server.url(path), dest_dir=dest, **kwargs)  # type: ignore[arg-type]
    return SingleStreamDownload(request, sink=events.append, progress_interval=0.01), events


def states(events: list[Event]) -> list[JobState]:
    return [e.state for e in events if isinstance(e, StateChanged)]


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- successful downloads --------------------------------------------------------


async def test_full_download(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&seed=4", tmp_path)
    result = await dl.run()
    assert result is not None
    assert result.path == tmp_path / "a.bin"
    assert result.size == SIZE
    assert result.sha256 == content_sha256(SIZE, 4) == sha_of(result.path)
    assert list(tmp_path.iterdir()) == [result.path]  # no partial file left
    assert states(events) == [JobState.PROBING, JobState.DOWNLOADING, JobState.COMPLETED]
    assert dl.state is JobState.COMPLETED
    finished = [e for e in events if isinstance(e, Finished)]
    assert finished and finished[0].sha256 == result.sha256


async def test_progress_is_monotonic_and_complete(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&rate=2M", tmp_path)
    await dl.run()
    progress = [e for e in events if isinstance(e, Progress)]
    assert len(progress) >= 2
    done = [p.downloaded for p in progress]
    assert done == sorted(done)
    assert progress[-1].downloaded == progress[-1].total == SIZE


@pytest.mark.parametrize("mode", ["both", "ext", "raw"])
async def test_utf8_content_disposition(server: FaultServer, tmp_path: Path, mode: str) -> None:
    dl, _ = make(server, f"/file/x.bin?size=1000&cd={quote(UTF8_NAME)}&cd_mode={mode}", tmp_path)
    result = await dl.run()
    assert result is not None
    assert result.path.name == UTF8_NAME
    assert result.sha256 == content_sha256(1000, 1)


async def test_percent_encoded_plain_filename(server: FaultServer, tmp_path: Path) -> None:
    double = quote(quote(UTF8_NAME), safe="")  # header carries filename="%E0%A6..."
    dl, _ = make(server, f"/file/x.bin?size=10&cd={double}&cd_mode=plain", tmp_path)
    result = await dl.run()
    assert result is not None and result.path.name == UTF8_NAME


async def test_user_filename_is_sanitized(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=10", tmp_path, filename="my:file?.bin")
    result = await dl.run()
    assert result is not None and result.path.name == "my_file_.bin"


async def test_filename_from_redirect_target(server: FaultServer, tmp_path: Path) -> None:
    target = quote("/file/final-name.bin?size=10", safe="")
    dl, _ = make(server, f"/redirect/2?to={target}", tmp_path)
    result = await dl.run()
    assert result is not None and result.path.name == "final-name.bin"


@pytest.mark.parametrize(
    "faults", ["length=chunked", "length=none&range=none", "gzip=1", "head=fail", "head=lie"]
)
async def test_unusual_servers(server: FaultServer, tmp_path: Path, faults: str) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}&{faults}", tmp_path)
    result = await dl.run()
    assert result is not None
    assert result.size == SIZE
    assert result.sha256 == content_sha256(SIZE, 1) == sha_of(result.path)


async def test_cookie_protected(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(
        server, "/protected/p.bin?size=100", tmp_path, cookies=f"{COOKIE_NAME}={COOKIE_VALUE}"
    )
    result = await dl.run()
    assert result is not None and result.size == 100


async def test_existing_file_is_not_overwritten(server: FaultServer, tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_text("keep me")
    dl, _ = make(server, "/file/a.bin?size=10", tmp_path)
    result = await dl.run()
    assert result is not None and result.path.name == "a (1).bin"
    assert (tmp_path / "a.bin").read_text() == "keep me"


async def test_creates_destination_folder(server: FaultServer, tmp_path: Path) -> None:
    dest = tmp_path / "new" / "sub"
    dl, _ = make(server, "/file/a.bin?size=10", dest)
    result = await dl.run()
    assert result is not None and result.path.parent == dest


# --- failures -------------------------------------------------------------------------


async def test_not_found(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, "/status/404", tmp_path)
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.NOT_FOUND
    assert dl.state is JobState.FAILED
    assert list(tmp_path.iterdir()) == []
    failed = [e for e in events if isinstance(e, Failed)]
    assert failed and failed[0].partial_path is None


async def test_connection_drop_keeps_partial(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&drop_at=70000", tmp_path)
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.NETWORK
    assert exc.value.retryable
    part = tmp_path / ("a.bin" + PARTIAL_SUFFIX)
    assert part.stat().st_size == 70_000
    failed = [e for e in events if isinstance(e, Failed)]
    assert failed and failed[0].partial_path == part


async def test_retry_after_failure_resumes(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}&drop_at=70000", tmp_path)
    with pytest.raises(DownloadError):
        await dl.run()
    result = await dl.run()  # resumes at byte 70000, which does not cross the drop point
    assert result is not None and result.sha256 == content_sha256(SIZE, 1)


async def test_not_enough_disk_space(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}", tmp_path)
    dl._disk_usage = lambda _path: SimpleNamespace(free=1000)  # type: ignore[assignment]
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.DISK_FULL
    assert list(tmp_path.iterdir()) == []


async def test_expired_link(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=10&expire_after=0", tmp_path)
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.LINK_EXPIRED


# --- pause, resume, cancel ----------------------------------------------------------------


def pause_after(dl: SingleStreamDownload, events: list[Event], nbytes: int) -> None:
    """Make the sink pause the download once ``nbytes`` have arrived."""

    def sink(event: Event) -> None:
        events.append(event)
        if isinstance(event, Progress) and event.downloaded >= nbytes and not events_paused:
            events_paused.append(True)
            dl.pause()

    events_paused: list[bool] = []
    dl._sink = sink


@pytest.mark.parametrize(
    ("faults", "seed"),
    [("", 1), ("&range=none", 1), ("&etag_after=2", content_seed(1, version=1))],
)
async def test_pause_and_resume(
    server: FaultServer, tmp_path: Path, faults: str, seed: int
) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&rate=1M{faults}", tmp_path)
    pause_after(dl, events, 100_000)
    assert await dl.run() is None
    assert dl.state is JobState.PAUSED
    part = tmp_path / ("a.bin" + PARTIAL_SUFFIX)
    paused_at = dl.downloaded
    assert part.stat().st_size == paused_at >= 100_000

    result = await dl.run()
    assert result is not None
    # range: continues; range=none: restarts; etag changed: If-Range fails, restarts
    # and gets the new content.
    assert result.sha256 == content_sha256(SIZE, seed) == sha_of(result.path)
    assert not part.exists()


async def test_resume_continues_from_offset(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&rate=1M", tmp_path)
    pause_after(dl, events, 100_000)
    await dl.run()
    paused_at = dl.downloaded
    events.clear()
    await dl.run()
    first = next(e for e in events if isinstance(e, Progress))
    assert first.downloaded >= paused_at


async def test_cancel_while_running(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&rate=1M", tmp_path)

    def sink(event: Event) -> None:
        events.append(event)
        if isinstance(event, Progress) and event.downloaded > 50_000:
            dl.cancel()

    dl._sink = sink
    assert await dl.run() is None
    assert dl.state is JobState.CANCELLED
    assert list(tmp_path.iterdir()) == []


async def test_cancel_while_paused(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}&rate=1M", tmp_path)
    pause_after(dl, events, 50_000)
    await dl.run()
    dl.cancel()
    assert dl.state is JobState.CANCELLED
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(RuntimeError):
        await dl.run()


async def test_external_cancellation_keeps_partial(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}&rate=500K", tmp_path)
    task = asyncio.create_task(dl.run())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dl.state is JobState.PAUSED
    assert (tmp_path / ("a.bin" + PARTIAL_SUFFIX)).exists()


async def test_run_twice_concurrently_is_rejected(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}&rate=1M", tmp_path)
    task = asyncio.create_task(dl.run())
    await asyncio.sleep(0.05)
    with pytest.raises(RuntimeError):
        await dl.run()
    dl.cancel()
    await task


async def test_pause_when_idle_is_a_no_op(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=10", tmp_path)
    dl.pause()
    assert dl.state is JobState.QUEUED
    result = await dl.run()
    assert result is not None
