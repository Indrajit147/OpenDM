"""Multi-connection HTTP download with crash-safe resume (spec 6.1, milestone M2).

Files next to the target (decision D8):
    name.ext.odm-part   preallocated data file, written at segment offsets
    name.ext.odm-state  checkpoint: validators and per-segment bytes written
    name.ext.odm-lock   OS lock held while a process works on the download

Checkpoints fsync the data before saving a state that claims it, so killing the
process (or losing power) never makes the state claim bytes that are not on disk.

``pause()``, ``cancel()`` and ``set_speed_limit()`` must be called from the event
loop that runs ``run()``.
"""

import asyncio
import contextlib
import dataclasses
import os
import random
import shutil
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Literal, TypeVar

from opendm.core.branding import LOCK_SUFFIX, PARTIAL_SUFFIX, STATE_SUFFIX
from opendm.core.checksum import file_digest, parse_checksum
from opendm.core.errors import DownloadError, ErrorKind, error_from_os, error_from_status
from opendm.core.events import EventSink, Failed, Finished, Progress, StateChanged, discard
from opendm.core.filenames import fit_to_path, sanitize_filename, unique_path
from opendm.core.models import DownloadRequest, DownloadResult, JobState, ProbeResult
from opendm.core.progress import Clock, SpeedMeter, Throttle, eta_seconds
from opendm.core.settings import EngineSettings
from opendm.core.units import format_bytes
from opendm.engine.http.planner import Segment, plan_segments, split_largest
from opendm.engine.http.probe import probe
from opendm.engine.http.ratelimit import TokenBucket, acquire_all
from opendm.engine.http.resume import (
    DownloadState,
    FileLock,
    load_state,
    mismatch_reason,
    save_state,
    url_hash,
)
from opendm.engine.http.retry import parse_retry_after
from opendm.engine.http.transport import HttpxTransport, Transport
from opendm.engine.http.writer import PartFile

T = TypeVar("T")
_FINAL_STATES = frozenset({JobState.COMPLETED, JobState.CANCELLED})


class _RangesIgnored(Exception):
    """A ranged request got the whole file (200) with an unchanged validator."""


class _Throttled(Exception):
    """429/503 while other connections are active: the server limits connections."""


def _changed(reason: str) -> str:
    return f"the file changed on the server ({reason}); restart to download it again"


def _range_start(content_range: str | None) -> int | None:
    """``bytes 500-999/1000`` -> 500."""
    if not content_range or not content_range.startswith("bytes "):
        return None
    try:
        return int(content_range[6:].split("-", 1)[0])
    except ValueError:
        return None


class HttpDownload:
    def __init__(
        self,
        request: DownloadRequest,
        *,
        settings: EngineSettings | None = None,
        sink: EventSink = discard,
        transport: Transport | None = None,
        global_limiter: TokenBucket | None = None,
        job_id: str | None = None,
        clock: Clock = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        if request.checksum:
            parse_checksum(request.checksum)  # fail fast on a malformed checksum
        self.request = request
        self.settings = settings or EngineSettings()
        self.job_id = job_id or uuid.uuid4().hex[:12]
        self.state = JobState.QUEUED
        self.probe_result: ProbeResult | None = None
        self.final_path: Path | None = None
        self.total: int | None = None
        self.segments: list[Segment] = []
        self.limiter = TokenBucket(request.speed_limit, clock=clock, sleep=sleep)
        self._global_limiter = global_limiter
        self._sink = sink
        self._transport = transport
        self._sleep = sleep
        self._rng = rng
        self._disk_usage = disk_usage
        self._meter = SpeedMeter(clock=clock)
        self._throttle = Throttle(self.settings.progress_interval, clock=clock)
        self._max_workers = self.settings.effective_connections()
        self._active = 0
        self._part: PartFile | None = None
        self._lock: FileLock | None = None
        self._persist_lock = threading.Lock()
        self._task: asyncio.Task[Any] | None = None
        self._stop: Literal["pause", "cancel"] | None = None

    # --- paths and status ------------------------------------------------------------------

    def _sibling(self, suffix: str) -> Path | None:
        if self.final_path is None:
            return None
        return self.final_path.with_name(self.final_path.name + suffix)

    @property
    def part_path(self) -> Path | None:
        return self._sibling(PARTIAL_SUFFIX)

    @property
    def state_path(self) -> Path | None:
        return self._sibling(STATE_SUFFIX)

    @property
    def downloaded(self) -> int:
        return sum(s.received for s in self.segments)

    @property
    def _ranged(self) -> bool:
        p = self.probe_result
        return p is not None and p.accepts_ranges and p.size is not None

    # --- control ---------------------------------------------------------------------------

    def pause(self) -> None:
        """Stop and keep the partial file and state. No-op when not running."""
        if self._task is not None and not self._task.done():
            self._stop = "pause"
            self._task.cancel()

    def cancel(self) -> None:
        """Stop and delete the partial file and state."""
        if self._task is not None and not self._task.done():
            self._stop = "cancel"
            self._task.cancel()
        elif self.state not in _FINAL_STATES:
            self._discard_files()
            self._set_state(JobState.CANCELLED)

    def restart(self) -> None:
        """Forget all progress (e.g. after VALIDATOR_CHANGED); ``run()`` starts over."""
        if self._task is not None:
            raise RuntimeError("pause the download before restarting it")
        if self.state in _FINAL_STATES:
            raise RuntimeError(f"download already {self.state}")
        self._discard_files()
        self.probe_result, self.final_path, self.total, self.segments = None, None, None, []
        self._set_state(JobState.QUEUED, "restarting from the beginning")

    def set_speed_limit(self, rate: int | None) -> None:
        self.limiter.rate = rate

    async def refresh(self, url: str, headers: Mapping[str, str] | None = None) -> None:
        """Continue from a new link (expired link flow). It must serve the same file."""
        if self._task is not None:
            raise RuntimeError("pause the download before refreshing its link")
        new_headers = dict(headers) if headers is not None else self.request.headers
        request = dataclasses.replace(self.request, url=url, headers=new_headers)
        transport = self._transport or HttpxTransport(verify=request.verify_tls)
        try:
            fresh = await self._retrying(
                lambda: probe(transport, request.url, request.request_headers())
            )
        finally:
            if self._transport is None:
                await transport.aclose()
        if self.probe_result is not None:
            old = DownloadState.from_probe(self.probe_result, [])
            reason = mismatch_reason(old, fresh)
            if reason:
                raise DownloadError(
                    ErrorKind.LINK_MISMATCH, f"new link is a different file: {reason}"
                )
            fresh = dataclasses.replace(fresh, filename=self.probe_result.filename)
            self.probe_result = fresh
        self.request = request
        self._set_state(self.state, "link refreshed")

    # --- main flow ---------------------------------------------------------------------------

    async def run(self) -> DownloadResult | None:
        """Download or resume. Returns None if paused or cancelled through this object.

        Raises DownloadError on failure, keeping the partial file and state so that
        ``run()`` can be called again. An outside cancellation (e.g. app exit) saves
        a checkpoint, leaves the job PAUSED and propagates.
        """
        if self.state in _FINAL_STATES:
            raise RuntimeError(f"download already {self.state}")
        if self._task is not None:
            raise RuntimeError("download is already running")
        self._task = asyncio.current_task()
        self._stop = None
        transport = self._transport or HttpxTransport(verify=self.request.verify_tls)
        try:
            await self._open(transport)
            self._set_state(JobState.DOWNLOADING)
            await self._download(transport)
            return await self._finish()
        except asyncio.CancelledError:
            self._checkpoint_now()
            if self._stop is None:
                self._set_state(JobState.PAUSED, "interrupted")
                raise
            if self._task is not None:
                self._task.uncancel()
            if self._stop == "cancel":
                self._close_files()
                self._discard_files()
                self._set_state(JobState.CANCELLED)
            else:
                self._set_state(JobState.PAUSED)
            return None
        except DownloadError as exc:
            self._checkpoint_now()
            self._fail(exc)
            raise
        except Exception as exc:
            self._checkpoint_now()
            error = DownloadError(ErrorKind.UNKNOWN, f"unexpected error: {exc!r}")
            self._fail(error)
            raise error from exc
        finally:
            self._close_files()
            self._task = None
            if self._transport is None:
                await transport.aclose()

    async def _open(self, transport: Transport) -> None:
        if self.probe_result is None or self.part_path is None or not self.part_path.exists():
            await self._prepare(transport)
            return
        self._acquire_lock()
        self._part = PartFile(self.part_path)
        try:
            self._part.open(create=False)
        except OSError as exc:
            raise error_from_os(exc) from exc

    async def _prepare(self, transport: Transport) -> None:
        """Probe, pick or adopt the target, lock it, check space, create the part file."""
        self._set_state(JobState.PROBING)
        request = self.request
        result = await self._retrying(
            lambda: probe(transport, request.url, request.request_headers())
        )
        try:
            final = self._choose_target(result)
            self.final_path = final
            self._acquire_lock()
            state = self._existing_state(result)
            written = state.written if state else 0
            if result.size is not None:
                free = self._disk_usage(final.parent).free
                if free < result.size - written:
                    raise DownloadError(
                        ErrorKind.DISK_FULL,
                        f"not enough free space: need {format_bytes(result.size - written)}, "
                        f"have {format_bytes(free)}",
                    )
            self.probe_result, self.total = result, result.size
            assert self.part_path is not None
            self._part = PartFile(self.part_path)
            if state is not None:
                self._part.open(create=False)
                self.segments = [Segment(s, e, w, w) for s, e, w in state.segments]
                self._set_state(JobState.PROBING, f"resuming at {format_bytes(written)}")
            else:
                self._part.open(create=True)
                self._part.truncate(0)
                if result.size is not None and result.accepts_ranges:
                    self._part.preallocate(result.size)
                self.segments = self._plan(result)
        except OSError as exc:
            raise error_from_os(exc) from exc
        self._checkpoint_now()

    def _choose_target(self, result: ProbeResult) -> Path:
        if self.request.part_file is not None:
            part = self.request.part_file
            if not part.name.endswith(PARTIAL_SUFFIX):
                raise DownloadError(ErrorKind.LINK_MISMATCH, f"not a partial download: {part}")
            return part.with_name(part.name[: -len(PARTIAL_SUFFIX)])
        name = (
            sanitize_filename(self.request.filename) if self.request.filename else result.filename
        )
        dest = self.request.dest_dir
        dest.mkdir(parents=True, exist_ok=True)
        name = fit_to_path(dest, name)
        candidate = dest / name
        state = load_state(candidate.with_name(name + STATE_SUFFIX))
        part = candidate.with_name(name + PARTIAL_SUFFIX)
        if state is not None and part.exists() and state.url_hash == url_hash(self.request.url):
            return candidate  # our own unfinished download: resume (or restart) it in place
        return unique_path(dest, name)

    def _existing_state(self, result: ProbeResult) -> DownloadState | None:
        """The checkpoint to continue from, or None to start from zero."""
        assert self.part_path is not None and self.state_path is not None
        state = load_state(self.state_path) if self.part_path.exists() else None
        if self.request.part_file is not None:
            if state is None:
                raise DownloadError(
                    ErrorKind.LINK_MISMATCH, f"no resumable download at {self.part_path}"
                )
            reason = mismatch_reason(state, result)
            if reason:
                raise DownloadError(ErrorKind.LINK_MISMATCH, f"link is a different file: {reason}")
            return state
        if state is None or self.request.restart:
            return None
        if not (state.accepts_ranges and result.accepts_ranges and result.size is not None):
            return None  # never resumable: just start over
        reason = mismatch_reason(state, result)
        if reason:
            raise DownloadError(ErrorKind.VALIDATOR_CHANGED, _changed(reason))
        return state

    def _plan(self, result: ProbeResult) -> list[Segment]:
        if result.size is not None and result.accepts_ranges:
            return plan_segments(result.size, self._max_workers, self.settings.min_segment)
        return [Segment(0, result.size)]

    async def _download(self, transport: Transport) -> None:
        checkpoints = asyncio.create_task(self._checkpoint_loop())
        try:
            while True:
                try:
                    await self._run_workers(transport)
                    return
                except _RangesIgnored:
                    self._fall_back_to_single(
                        "the server ignores byte ranges; using one connection"
                    )
        finally:
            checkpoints.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await checkpoints

    def _fall_back_to_single(self, message: str) -> None:
        assert self.probe_result is not None
        self.probe_result = dataclasses.replace(self.probe_result, accepts_ranges=False)
        self.segments = [Segment(0, self.total)]
        if self.state_path is not None:
            with contextlib.suppress(OSError):
                self.state_path.unlink(missing_ok=True)
        self._set_state(JobState.DOWNLOADING, message)

    async def _run_workers(self, transport: Transport) -> None:
        queue = [s for s in self.segments if not s.complete]
        active: dict[asyncio.Task[bool], Segment] = {}
        try:
            while True:
                while len(active) < self._max_workers:
                    seg: Segment | None = None
                    if queue:
                        seg = queue.pop(0)
                    elif self._ranged and active:
                        seg = split_largest(self.segments, self.settings.min_segment)
                    if seg is None:
                        break
                    active[asyncio.create_task(self._worker(transport, seg))] = seg
                if not active:
                    return
                done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    seg = active.pop(task)
                    exc = task.exception()
                    if exc is None:
                        continue
                    if isinstance(exc, _Throttled) and active:
                        self._max_workers = max(1, len(active))
                        queue.insert(0, seg)
                        self._set_state(
                            JobState.DOWNLOADING,
                            f"server limits connections; using {self._max_workers}",
                        )
                        continue
                    raise exc
        finally:
            for task in active:
                task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)

    async def _worker(self, transport: Transport, seg: Segment) -> bool:
        """Download one segment, retrying retryable errors with backoff."""
        self._active += 1
        try:
            attempt = 0
            while not seg.complete:
                before = seg.received
                try:
                    if await self._fetch(transport, seg):
                        seg.end = seg.start + seg.written  # unknown size: stream ended
                        return True
                    if not seg.complete:
                        raise DownloadError(ErrorKind.NETWORK, "connection closed early")
                except DownloadError as exc:
                    if seg.received > before:
                        attempt = 0  # progress was made; this is a fresh failure
                    if exc.status in (429, 503) and self._active > 1:
                        raise _Throttled from exc
                    if not exc.retryable or attempt >= self.settings.retry.max_retries:
                        raise
                    delay = self.settings.retry.wait_for(attempt, exc.retry_after, self._rng)
                    attempt += 1
                    self._set_state(
                        JobState.DOWNLOADING, f"{exc.message}; retrying in {delay:.1f} s"
                    )
                    await self._sleep(delay)
            return True
        finally:
            self._active -= 1

    async def _fetch(self, transport: Transport, seg: Segment) -> bool:
        """One GET for ``seg``. Returns True if an unknown-length body ended."""
        assert self.probe_result is not None
        ranged = self._ranged
        headers = self.request.request_headers()
        if ranged:
            assert seg.end is not None
            headers["Range"] = f"bytes={seg.pos}-{seg.end - 1}"
            if self.probe_result.validator:
                headers["If-Range"] = self.probe_result.validator
        else:
            seg.received = seg.written = 0  # no ranges: always from the start

        async with transport.stream("GET", self.request.url, headers) as resp:
            if ranged and resp.status == 206:
                if _range_start(resp.headers.get("content-range")) != seg.pos:
                    raise DownloadError(ErrorKind.HTTP_CLIENT, "server sent the wrong byte range")
            elif 200 <= resp.status < 300 and resp.status != 206:
                if ranged:
                    reason = self._validator_change(resp.headers)
                    if reason:
                        raise DownloadError(ErrorKind.VALIDATOR_CHANGED, _changed(reason))
                    if not (seg.pos == 0 and len(self.segments) == 1):
                        raise _RangesIgnored
            elif resp.status == 206:
                raise DownloadError(ErrorKind.HTTP_CLIENT, "unexpected partial response")
            else:
                retry_after = parse_retry_after(resp.headers.get("retry-after"))
                raise error_from_status(resp.status, retry_after)

            buffer = bytearray()
            try:
                async for chunk in resp.aiter_bytes():
                    if seg.end is not None:
                        room = seg.end - seg.pos  # the segment may have been split meanwhile
                        if room <= 0:
                            break
                        chunk = chunk[:room]
                    await acquire_all((self.limiter, self._global_limiter), len(chunk))
                    buffer += chunk
                    seg.received += len(chunk)
                    self._on_bytes()
                    if len(buffer) >= self.settings.buffer_size:
                        await self._flush(seg, buffer)
                    if seg.end is not None and seg.pos >= seg.end:
                        break
                await self._flush(seg, buffer)
            finally:
                if buffer:  # error or cancellation: keep what arrived
                    with contextlib.suppress(OSError, RuntimeError):
                        assert self._part is not None
                        self._part.write_at(seg.start + seg.written, bytes(buffer))
                        seg.written += len(buffer)
                seg.received = seg.written
        return seg.end is None

    def _validator_change(self, headers: Mapping[str, str]) -> str | None:
        assert self.probe_result is not None
        old_etag, new_etag = self.probe_result.etag, headers.get("etag")
        if old_etag and new_etag:
            return None if old_etag == new_etag else "ETag changed"
        old_lm, new_lm = self.probe_result.last_modified, headers.get("last-modified")
        if old_lm and new_lm and old_lm != new_lm:
            return "Last-Modified changed"
        return None

    async def _flush(self, seg: Segment, buffer: bytearray) -> None:
        if not buffer:
            return
        assert self._part is not None
        data = bytes(buffer)
        buffer.clear()
        try:
            await asyncio.to_thread(self._part.write_at, seg.start + seg.written, data)
        except OSError as exc:
            raise error_from_os(exc) from exc
        seg.written += len(data)

    async def _finish(self) -> DownloadResult:
        assert self.final_path is not None and self.part_path is not None and self._part
        if self.total is not None and self.downloaded != self.total:
            raise DownloadError(ErrorKind.NETWORK, "download ended before the file was complete")
        self._emit_progress()
        self._set_state(JobState.VERIFYING)
        try:
            await asyncio.to_thread(self._part.sync)
            self._close_files(release_lock=False)
            sha256 = await asyncio.to_thread(file_digest, self.part_path, "sha256")
            expected = parse_checksum(self.request.checksum) if self.request.checksum else None
            actual = None
            if expected is not None:
                algo = expected[0]
                actual = (
                    sha256
                    if algo == "sha256"
                    else await asyncio.to_thread(file_digest, self.part_path, algo)
                )
            final = self.final_path
            if final.exists():  # something appeared there meanwhile
                final = unique_path(final.parent, final.name)
            os.replace(self.part_path, final)
            assert self.state_path is not None
            self.state_path.unlink(missing_ok=True)
        except OSError as exc:
            raise error_from_os(exc) from exc
        self.final_path = final
        self.total = self.downloaded
        if expected is not None and actual != expected[1]:
            raise DownloadError(
                ErrorKind.CHECKSUM_MISMATCH,
                f"{expected[0]} mismatch for {final.name}: expected {expected[1]}, got {actual}",
            )
        self._set_state(JobState.COMPLETED)
        result = DownloadResult(final, self.total, sha256)
        self._sink(Finished(self.job_id, result.path, result.size, result.sha256))
        return result

    # --- checkpoints -----------------------------------------------------------------------------

    def _snapshot(self) -> DownloadState | None:
        if not self._ranged or self._part is None or not self._part.is_open:
            return None
        assert self.probe_result is not None
        segments = [(s.start, s.end, s.written) for s in self.segments]
        return DownloadState.from_probe(self.probe_result, segments)

    def _persist(self, state: DownloadState) -> None:
        """fsync the data, then save the state that describes it."""
        with self._persist_lock:
            if self._part is None or not self._part.is_open or self.state_path is None:
                return
            self._part.sync()
            save_state(self.state_path, state)

    def _checkpoint_now(self) -> None:
        state = self._snapshot()
        if state is not None:
            with contextlib.suppress(OSError):
                self._persist(state)

    async def _checkpoint_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.state_interval)
            state = self._snapshot()
            if state is not None:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(self._persist, state)

    # --- helpers ----------------------------------------------------------------------

    async def _retrying(self, attempt_fn: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            try:
                return await attempt_fn()
            except DownloadError as exc:
                if not exc.retryable or attempt >= self.settings.retry.max_retries:
                    raise
                delay = self.settings.retry.wait_for(attempt, exc.retry_after, self._rng)
                attempt += 1
                self._set_state(self.state, f"{exc.message}; retrying in {delay:.1f} s")
                await self._sleep(delay)

    def _acquire_lock(self) -> None:
        lock_path = self._sibling(LOCK_SUFFIX)
        assert lock_path is not None
        lock = FileLock(lock_path)
        try:
            lock.acquire()
        except OSError as exc:
            raise error_from_os(exc) from exc
        self._lock = lock

    def _close_files(self, release_lock: bool = True) -> None:
        with self._persist_lock:
            if self._part is not None:
                self._part.close()
        if release_lock and self._lock is not None:
            self._lock.release()
            self._lock = None

    def _discard_files(self) -> None:
        for path in (self.part_path, self.state_path):
            if path is not None:
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
                    path.with_name(path.name + ".tmp").unlink(missing_ok=True)

    def _on_bytes(self) -> None:
        self._meter.update(self.downloaded)
        if self._throttle.ready():
            self._emit_progress()

    def _emit_progress(self) -> None:
        downloaded = self.downloaded
        speed = self._meter.speed()
        segments = tuple((s.start, s.end, s.received) for s in self.segments)
        self._sink(
            Progress(
                self.job_id,
                downloaded,
                self.total,
                speed,
                eta_seconds(self.total, downloaded, speed),
                self._active,
                segments,
            )
        )

    def _set_state(self, state: JobState, message: str = "") -> None:
        self.state = state
        self._sink(StateChanged(self.job_id, state, message))

    def _fail(self, error: DownloadError) -> None:
        self._set_state(JobState.FAILED, error.message)
        part = self.part_path
        self._sink(Failed(self.job_id, error, part if part and part.exists() else None))
