"""HttpDownload (multi-connection engine) against the local test server."""

import asyncio
import hashlib
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from opendm.core.branding import LOCK_SUFFIX, PARTIAL_SUFFIX, STATE_SUFFIX
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.events import Event, Failed, Finished, Progress, StateChanged
from opendm.core.models import DownloadRequest, JobState
from opendm.core.settings import EngineSettings, RetryPolicy
from opendm.engine.http.download import HttpDownload
from opendm.engine.http.resume import FileLock, load_state
from tests.server.app import COOKIE_NAME, COOKIE_VALUE, FaultServer, content_seed, content_sha256

KIB = 1024
MIB = 1024 * KIB
SIZE = 300_000
UTF8_NAME = "রিপোর্ট € file.pdf"
# Bytes the server already pushed into sockets when a run is paused; they are lost
# and fetched again, which is fine, but nothing else may be downloaded twice.
IN_FLIGHT = 256 * KIB
FAST_RETRY = RetryPolicy(max_retries=5, base_delay=0.01, max_delay=0.05, max_retry_after=0.1)


def settings(**overrides: object) -> EngineSettings:
    values: dict[str, object] = {
        "connections": 4,
        "min_segment": 64 * KIB,
        "buffer_size": 64 * KIB,
        "state_interval": 0.1,
        "progress_interval": 0.01,
        "retry": FAST_RETRY,
    }
    values.update(overrides)
    return EngineSettings(**values)  # type: ignore[arg-type]


def make(
    server: FaultServer, path: str, dest: Path, cfg: EngineSettings | None = None, **kwargs: object
) -> tuple[HttpDownload, list[Event]]:
    events: list[Event] = []
    request = DownloadRequest(url=server.url(path), dest_dir=dest, **kwargs)  # type: ignore[arg-type]
    return HttpDownload(request, settings=cfg or settings(), sink=events.append), events


def states(events: list[Event]) -> list[JobState]:
    return [e.state for e in events if isinstance(e, StateChanged)]


def messages(events: list[Event]) -> str:
    return " | ".join(e.message for e in events if isinstance(e, StateChanged))


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def leftovers(dest: Path) -> list[str]:
    return sorted(p.name for p in dest.iterdir() if p.suffix in (PARTIAL_SUFFIX, STATE_SUFFIX))


# --- multi-connection ---------------------------------------------------------------------


async def test_100mb_over_8_connections(server: FaultServer, tmp_path: Path) -> None:
    path = "/file/big.bin?size=100M&seed=9"
    cfg = settings(connections=8, min_segment=MIB, buffer_size=MIB)
    dl, events = make(server, path, tmp_path, cfg)
    result = await dl.run()
    assert result is not None
    assert result.size == 100 * MIB
    assert result.sha256 == content_sha256(100 * MIB, 9) == sha_of(result.path)
    assert server.stats(path)["peak"] == 8
    assert max(e.connections for e in events if isinstance(e, Progress)) == 8
    assert leftovers(tmp_path) == []
    assert not (tmp_path / ("big.bin" + LOCK_SUFFIX)).exists()


async def test_dynamic_splitting_fills_free_connections(server: FaultServer, tmp_path) -> None:
    # One connection gets a third of the way, then a 4-connection run must split the
    # single remaining segment to use all four.
    path = "/file/s.bin?size=2M&rate=2M"
    first, events = make(server, path, tmp_path, settings(connections=1))
    pause_after(first, events, 600_000)
    await first.run()
    second, _ = make(server, path, tmp_path, settings(connections=4))
    result = await second.run()
    assert result is not None and result.sha256 == content_sha256(2 * MIB, 1)
    assert len(second.segments) >= 4
    assert server.stats(path)["peak"] >= 4


async def test_progress_carries_segment_map(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, "/file/s.bin?size=1M&rate=2M", tmp_path)
    await dl.run()
    progress = [e for e in events if isinstance(e, Progress)]
    done = [p.downloaded for p in progress]
    assert done == sorted(done)
    assert progress[-1].downloaded == progress[-1].total == MIB
    assert any(len(p.segments) == 4 for p in progress)


async def test_states(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, f"/file/a.bin?size={SIZE}", tmp_path)
    await dl.run()
    assert [s for s in states(events) if s is not JobState.DOWNLOADING] == [
        JobState.PROBING,
        JobState.VERIFYING,
        JobState.COMPLETED,
    ]
    assert isinstance(events[-1], Finished)


# --- names and odd servers (carried over from M1) -------------------------------------------


@pytest.mark.parametrize("mode", ["both", "ext", "raw"])
async def test_utf8_content_disposition(server: FaultServer, tmp_path: Path, mode: str) -> None:
    dl, _ = make(server, f"/file/x.bin?size=1000&cd={quote(UTF8_NAME)}&cd_mode={mode}", tmp_path)
    result = await dl.run()
    assert result is not None and result.path.name == UTF8_NAME


async def test_user_filename_and_redirect(server: FaultServer, tmp_path: Path) -> None:
    target = quote("/file/final-name.bin?size=10", safe="")
    dl, _ = make(server, f"/redirect/2?to={target}", tmp_path)
    assert (await dl.run()).path.name == "final-name.bin"  # type: ignore[union-attr]
    dl, _ = make(server, "/file/a.bin?size=10", tmp_path, filename="my:file?.bin")
    assert (await dl.run()).path.name == "my_file_.bin"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "faults",
    [
        "range=none",  # no Range support: one connection
        "range=ignore",  # 200 instead of 206: falls back to one connection
        "length=chunked",
        "length=none&range=none",
        "gzip=1",
        "head=fail",
        "head=lie",
    ],
)
async def test_fallbacks(server: FaultServer, tmp_path: Path, faults: str) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}&{faults}", tmp_path)
    result = await dl.run()
    assert result is not None
    assert result.size == SIZE
    assert result.sha256 == content_sha256(SIZE, 1) == sha_of(result.path)
    assert leftovers(tmp_path) == []


async def test_200_instead_of_206_is_reported(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, "/file/a.bin?size=1M&range=ignore", tmp_path)
    await dl.run()
    assert "ignores byte ranges" in messages(events)


async def test_cookie_protected(server: FaultServer, tmp_path: Path) -> None:
    cookie = f"{COOKIE_NAME}={COOKIE_VALUE}"
    dl, _ = make(server, "/protected/p.bin?size=1M", tmp_path, cookies=cookie)
    result = await dl.run()
    assert result is not None and result.sha256 == content_sha256(MIB, 1)


async def test_existing_file_is_not_overwritten(server: FaultServer, tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_text("keep me")
    dl, _ = make(server, "/file/a.bin?size=10", tmp_path)
    result = await dl.run()
    assert result is not None and result.path.name == "a (1).bin"
    assert (tmp_path / "a.bin").read_text() == "keep me"


# --- retries and failures --------------------------------------------------------------------


async def test_retries_injected_server_errors(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=1M&fail_first=3", tmp_path)
    result = await dl.run()
    assert result is not None and result.sha256 == content_sha256(MIB, 1)


async def test_connection_drop_is_retried_from_the_drop_point(
    server: FaultServer, tmp_path
) -> None:
    path = "/file/a.bin?size=1M&drop_at=300000"
    dl, _ = make(server, path, tmp_path, settings(connections=1))
    result = await dl.run()
    assert result is not None and result.sha256 == content_sha256(MIB, 1)
    assert server.stats(path)["bytes_sent"] == MIB  # nothing downloaded twice


async def test_gives_up_after_max_retries_and_keeps_partial(server: FaultServer, tmp_path) -> None:
    cfg = settings(connections=1, retry=RetryPolicy(max_retries=0))
    dl, events = make(server, f"/file/a.bin?size={SIZE}&drop_at=70000", tmp_path, cfg)
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.NETWORK
    part = tmp_path / ("a.bin" + PARTIAL_SUFFIX)
    assert part.exists()
    state = load_state(tmp_path / ("a.bin" + STATE_SUFFIX))
    assert state is not None and state.written == 70_000
    failed = [e for e in events if isinstance(e, Failed)]
    assert failed and failed[0].partial_path == part
    result = await dl.run()  # calling run() again resumes
    assert result is not None and result.sha256 == content_sha256(SIZE, 1)


async def test_not_found_is_not_retried(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/status/404", tmp_path)
    t0 = time.perf_counter()
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.NOT_FOUND
    assert time.perf_counter() - t0 < 1  # no retry delays
    assert list(tmp_path.iterdir()) == []


async def test_server_connection_limit_reduces_connections(server: FaultServer, tmp_path) -> None:
    path = "/file/a.bin?size=2M&rate=4M&max_conn=3&retry_after=0"
    dl, events = make(server, path, tmp_path, settings(connections=8))
    result = await dl.run()
    assert result is not None and result.sha256 == content_sha256(2 * MIB, 1)
    assert "limits connections" in messages(events)


async def test_not_enough_disk_space(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}", tmp_path)
    dl._disk_usage = lambda _path: SimpleNamespace(free=1000)  # type: ignore[assignment]
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.DISK_FULL
    assert list(tmp_path.iterdir()) == []


# --- validators, expired links ---------------------------------------------------------------


async def test_etag_change_is_detected_then_restart(server: FaultServer, tmp_path: Path) -> None:
    # HEAD is request 1, the four range GETs are 2-5; afterwards the file "changes".
    path = "/file/a.bin?size=1M&rate=2M&etag_after=5"
    dl, events = make(server, path, tmp_path, settings(connections=4, min_segment=256 * KIB))
    pause_after(dl, events, 100_000)
    await dl.run()
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.VALIDATOR_CHANGED
    assert (tmp_path / ("a.bin" + PARTIAL_SUFFIX)).exists()  # kept until the user decides
    dl.restart()
    result = await dl.run()
    assert result is not None
    assert result.sha256 == content_sha256(MIB, content_seed(1, version=1))


EXPIRING = "/file/a.bin?size=1M&rate=256K&expire_after=0.3"  # rejects requests after 0.3 s


async def run_until_expired(dl: HttpDownload, events: list[Event]) -> DownloadError:
    """Pause early, wait past the expiry, resume: the new requests get 403."""
    pause_after(dl, events, 100_000)
    await dl.run()
    await asyncio.sleep(0.35)
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    return exc.value


async def test_expired_link_then_refresh(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, EXPIRING, tmp_path)
    error = await run_until_expired(dl, events)
    assert error.kind is ErrorKind.LINK_EXPIRED
    assert not error.retryable
    kept = dl.downloaded
    await dl.refresh(server.url("/file/a.bin?size=1M&rate=1M"))
    result = await dl.run()
    assert result is not None and result.sha256 == content_sha256(MIB, 1)
    assert kept > 0


async def test_refresh_to_a_different_file_is_rejected(server: FaultServer, tmp_path) -> None:
    dl, events = make(server, EXPIRING, tmp_path)
    await run_until_expired(dl, events)
    with pytest.raises(DownloadError) as exc:
        await dl.refresh(server.url("/file/a.bin?size=2M"))
    assert exc.value.kind is ErrorKind.LINK_MISMATCH


# --- speed limit -----------------------------------------------------------------------------


async def test_speed_limit_within_10_percent(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=3M", tmp_path, speed_limit=MIB)
    t0 = time.perf_counter()
    result = await dl.run()
    elapsed = time.perf_counter() - t0
    assert result is not None and result.sha256 == content_sha256(3 * MIB, 1)
    assert 2.7 <= elapsed <= 3.3


async def test_speed_limit_can_change_while_running(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=2M", tmp_path, speed_limit=256 * KIB)
    task = asyncio.create_task(dl.run())
    await asyncio.sleep(0.3)
    dl.set_speed_limit(None)
    t0 = time.perf_counter()
    assert await task is not None
    assert time.perf_counter() - t0 < 2  # would take ~7 s at the old limit


# --- checksums ---------------------------------------------------------------------------------


async def test_checksum_match(server: FaultServer, tmp_path: Path) -> None:
    good = f"sha256:{content_sha256(SIZE, 1)}"
    dl, _ = make(server, f"/file/a.bin?size={SIZE}", tmp_path, checksum=good)
    assert await dl.run() is not None


async def test_checksum_mismatch(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, f"/file/a.bin?size={SIZE}", tmp_path, checksum="md5:" + "0" * 32)
    with pytest.raises(DownloadError) as exc:
        await dl.run()
    assert exc.value.kind is ErrorKind.CHECKSUM_MISMATCH
    assert dl.state is JobState.FAILED
    assert (tmp_path / "a.bin").exists()  # decision M2-3: kept under its final name
    assert leftovers(tmp_path) == []


# --- pause, resume, cancel, lock ---------------------------------------------------------------


def pause_after(dl: HttpDownload, events: list[Event], nbytes: int) -> None:
    fired: list[bool] = []

    def sink(event: Event) -> None:
        events.append(event)
        if isinstance(event, Progress) and event.downloaded >= nbytes and not fired:
            fired.append(True)
            dl.pause()

    dl._sink = sink


@pytest.mark.parametrize("faults", ["", "&range=none"])
async def test_pause_and_resume(server: FaultServer, tmp_path: Path, faults: str) -> None:
    path = f"/file/a.bin?size=1M&rate=2M{faults}"
    dl, events = make(server, path, tmp_path)
    pause_after(dl, events, 200_000)
    assert await dl.run() is None
    assert dl.state is JobState.PAUSED
    assert (tmp_path / ("a.bin" + PARTIAL_SUFFIX)).exists()
    result = await dl.run()
    assert result is not None and result.sha256 == content_sha256(MIB, 1)
    assert leftovers(tmp_path) == []


async def test_resume_does_not_redownload(server: FaultServer, tmp_path: Path) -> None:
    path = "/file/a.bin?size=1M&rate=2M"
    dl, events = make(server, path, tmp_path)
    pause_after(dl, events, 300_000)
    await dl.run()
    await dl.run()
    assert server.stats(path)["bytes_sent"] <= MIB + IN_FLIGHT


async def test_new_process_resumes_from_state_file(server: FaultServer, tmp_path: Path) -> None:
    path = "/file/a.bin?size=1M&rate=2M"
    first, events = make(server, path, tmp_path)
    pause_after(first, events, 300_000)
    await first.run()
    written = load_state(tmp_path / ("a.bin" + STATE_SUFFIX)).written  # type: ignore[union-attr]
    assert written > 0
    second, _ = make(server, path, tmp_path)  # same URL and folder, fresh object
    result = await second.run()
    assert result is not None and result.path.name == "a.bin"
    assert result.sha256 == content_sha256(MIB, 1)
    assert server.stats(path)["bytes_sent"] <= MIB + IN_FLIGHT


async def test_restart_flag_discards_partial(server: FaultServer, tmp_path: Path) -> None:
    path = "/file/a.bin?size=1M&rate=2M"
    first, events = make(server, path, tmp_path)
    pause_after(first, events, 300_000)
    await first.run()
    second, _ = make(server, path, tmp_path, restart=True)
    result = await second.run()
    assert result is not None and result.path.name == "a.bin"
    assert result.sha256 == content_sha256(MIB, 1)


async def test_continue_part_file_from_new_url(server: FaultServer, tmp_path: Path) -> None:
    first, events = make(server, EXPIRING, tmp_path)
    await run_until_expired(first, events)
    part = tmp_path / ("a.bin" + PARTIAL_SUFFIX)
    second, _ = make(server, "/file/other-name?size=1M", tmp_path, part_file=part)
    result = await second.run()
    assert result is not None and result.path == tmp_path / "a.bin"
    assert result.sha256 == content_sha256(MIB, 1)


async def test_second_process_is_locked_out(server: FaultServer, tmp_path: Path) -> None:
    path = "/file/a.bin?size=1M&rate=1M"
    first, events = make(server, path, tmp_path)
    pause_after(first, events, 100_000)
    await first.run()
    lock = FileLock(tmp_path / ("a.bin" + LOCK_SUFFIX))
    lock.acquire()  # simulate another process holding the download
    try:
        second, _ = make(server, path, tmp_path)
        with pytest.raises(DownloadError) as exc:
            await second.run()
        assert exc.value.kind is ErrorKind.IN_USE
    finally:
        lock.release()


async def test_cancel_while_running(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, "/file/a.bin?size=1M&rate=1M", tmp_path)

    def sink(event: Event) -> None:
        events.append(event)
        if isinstance(event, Progress) and event.downloaded > 100_000:
            dl.cancel()

    dl._sink = sink
    assert await dl.run() is None
    assert dl.state is JobState.CANCELLED
    assert list(tmp_path.iterdir()) == []


async def test_cancel_while_paused(server: FaultServer, tmp_path: Path) -> None:
    dl, events = make(server, "/file/a.bin?size=1M&rate=1M", tmp_path)
    pause_after(dl, events, 100_000)
    await dl.run()
    dl.cancel()
    assert dl.state is JobState.CANCELLED
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(RuntimeError):
        await dl.run()


async def test_external_cancellation_checkpoints(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=1M&rate=1M", tmp_path)
    task = asyncio.create_task(dl.run())
    await asyncio.sleep(0.4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dl.state is JobState.PAUSED
    state = load_state(tmp_path / ("a.bin" + STATE_SUFFIX))
    assert state is not None and state.written > 0


async def test_run_twice_concurrently_is_rejected(server: FaultServer, tmp_path: Path) -> None:
    dl, _ = make(server, "/file/a.bin?size=1M&rate=1M", tmp_path)
    task = asyncio.create_task(dl.run())
    await asyncio.sleep(0.05)
    with pytest.raises(RuntimeError):
        await dl.run()
    dl.cancel()
    await task
