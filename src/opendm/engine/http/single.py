"""Single-connection HTTP download with in-session pause/resume (milestone M1).

Data goes to ``<name>.odm-part`` next to the target and is renamed on completion.
Pause keeps the partial file; resume asks for the remaining bytes with ``Range``
and ``If-Range`` and restarts from zero if the server can't or won't continue.
Crash-safe resume (state sidecar) and multiple connections arrive in M2.

``pause()`` and ``cancel()`` must be called from the event loop running ``run()``.
"""

import asyncio
import contextlib
import hashlib
import os
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from opendm.core.branding import PARTIAL_SUFFIX
from opendm.core.errors import (
    DownloadError,
    ErrorKind,
    error_from_os,
    error_from_status,
)
from opendm.core.events import EventSink, Failed, Finished, Progress, StateChanged, discard
from opendm.core.filenames import fit_to_path, sanitize_filename, unique_path
from opendm.core.models import DownloadRequest, DownloadResult, JobState, ProbeResult
from opendm.core.progress import Clock, SpeedMeter, Throttle, eta_seconds
from opendm.core.units import format_bytes
from opendm.engine.http.probe import content_length, probe, total_from_content_range
from opendm.engine.http.transport import HttpxTransport, Transport

_FINAL_STATES = frozenset({JobState.COMPLETED, JobState.CANCELLED})


def _range_start(content_range: str | None) -> int | None:
    """``bytes 500-999/1000`` -> 500."""
    if not content_range or not content_range.startswith("bytes "):
        return None
    try:
        return int(content_range[6:].split("-", 1)[0])
    except ValueError:
        return None


class SingleStreamDownload:
    def __init__(
        self,
        request: DownloadRequest,
        *,
        sink: EventSink = discard,
        transport: Transport | None = None,
        job_id: str | None = None,
        progress_interval: float = 0.25,
        clock: Clock = time.monotonic,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        self.request = request
        self.job_id = job_id or uuid.uuid4().hex[:12]
        self.state = JobState.QUEUED
        self.probe_result: ProbeResult | None = None
        self.final_path: Path | None = None
        self.downloaded = 0
        self.total: int | None = None
        self._sink = sink
        self._transport = transport
        self._disk_usage = disk_usage
        self._meter = SpeedMeter(clock=clock)
        self._throttle = Throttle(progress_interval, clock=clock)
        self._hasher = hashlib.sha256()
        self._task: asyncio.Task[Any] | None = None
        self._stop: Literal["pause", "cancel"] | None = None

    @property
    def part_path(self) -> Path | None:
        if self.final_path is None:
            return None
        return self.final_path.with_name(self.final_path.name + PARTIAL_SUFFIX)

    # --- control -------------------------------------------------------------------

    def pause(self) -> None:
        """Stop transferring and keep the partial file. No-op when not running."""
        if self._task is not None and not self._task.done():
            self._stop = "pause"
            self._task.cancel()

    def cancel(self) -> None:
        """Stop and delete the partial file."""
        if self._task is not None and not self._task.done():
            self._stop = "cancel"
            self._task.cancel()
        elif self.state not in _FINAL_STATES:
            self._discard_partial()
            self._set_state(JobState.CANCELLED)

    # --- main flow ----------------------------------------------------------------------

    async def run(self) -> DownloadResult | None:
        """Download (or resume). Returns None if paused or cancelled via this object.

        Raises DownloadError on failure; the partial file is kept so ``run()`` can be
        called again. An outside cancellation leaves the job PAUSED and propagates.
        """
        if self.state in _FINAL_STATES:
            raise RuntimeError(f"download already {self.state}")
        if self._task is not None:
            raise RuntimeError("download is already running")
        self._task = asyncio.current_task()
        self._stop = None
        transport = self._transport or HttpxTransport(verify=self.request.verify_tls)
        try:
            if self.probe_result is None:
                await self._prepare(transport)
            self._set_state(JobState.DOWNLOADING)
            await self._transfer(transport)
            return self._finish()
        except asyncio.CancelledError:
            if self._stop is None:
                self._set_state(JobState.PAUSED, "interrupted")
                raise
            if self._task is not None:
                self._task.uncancel()
            if self._stop == "cancel":
                self._discard_partial()
                self._set_state(JobState.CANCELLED)
            else:
                self._set_state(JobState.PAUSED)
            return None
        except DownloadError as exc:
            self._fail(exc)
            raise
        except Exception as exc:
            error = DownloadError(ErrorKind.UNKNOWN, f"unexpected error: {exc!r}")
            self._fail(error)
            raise error from exc
        finally:
            self._task = None
            if self._transport is None:
                await transport.aclose()

    async def _prepare(self, transport: Transport) -> None:
        """Probe, pick the target path and check free space. Reserves the name."""
        self._set_state(JobState.PROBING)
        result = await probe(transport, self.request.url, self.request.request_headers())
        name = result.filename
        if self.request.filename:
            name = sanitize_filename(self.request.filename)
        dest = self.request.dest_dir
        try:
            dest.mkdir(parents=True, exist_ok=True)
            if result.size is not None:
                free = self._disk_usage(dest).free
                if free < result.size:
                    raise DownloadError(
                        ErrorKind.DISK_FULL,
                        f"not enough free space: need {format_bytes(result.size)}, "
                        f"have {format_bytes(free)}",
                    )
            self.final_path = unique_path(dest, fit_to_path(dest, name))
            assert self.part_path is not None
            self.part_path.touch(exist_ok=False)
        except OSError as exc:
            raise error_from_os(exc) from exc
        self.probe_result = result
        self.total = result.size

    async def _transfer(self, transport: Transport) -> None:
        assert self.probe_result is not None and self.part_path is not None
        headers = self.request.request_headers()
        offset = self.downloaded if self.probe_result.accepts_ranges else 0
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if self.probe_result.validator:
                headers["If-Range"] = self.probe_result.validator

        async with transport.stream("GET", self.request.url, headers) as resp:
            if resp.status == 206 and offset:
                if _range_start(resp.headers.get("content-range")) != offset:
                    raise DownloadError(ErrorKind.HTTP_CLIENT, "server sent the wrong byte range")
                total = total_from_content_range(resp.headers.get("content-range")) or self.total
                mode = "r+b"
            elif 200 <= resp.status < 300 and resp.status != 206:
                if self.downloaded:
                    self._set_state(JobState.DOWNLOADING, "server cannot resume; restarting")
                offset, total, mode = 0, content_length(resp.headers), "wb"
                self._hasher = hashlib.sha256()
            elif resp.status == 206:
                raise DownloadError(ErrorKind.HTTP_CLIENT, "unexpected partial response")
            else:
                raise error_from_status(resp.status)

            self.downloaded, self.total = offset, total
            self._meter.reset(offset)
            try:
                with open(self.part_path, mode) as f:
                    if mode == "r+b":
                        f.seek(offset)
                        f.truncate()
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
                        self._hasher.update(chunk)
                        self.downloaded += len(chunk)
                        self._meter.update(self.downloaded)
                        if self._throttle.ready():
                            self._emit_progress()
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as exc:
                raise error_from_os(exc) from exc

        if self.total is not None and self.downloaded != self.total:
            raise DownloadError(
                ErrorKind.NETWORK,
                f"connection closed after {self.downloaded} of {self.total} bytes",
            )

    def _finish(self) -> DownloadResult:
        assert self.final_path is not None and self.part_path is not None
        final = self.final_path
        if final.exists():  # something appeared there while we were downloading
            final = unique_path(final.parent, final.name)
        try:
            os.replace(self.part_path, final)
        except OSError as exc:
            raise error_from_os(exc) from exc
        self.final_path = final
        self.total = self.downloaded
        self._emit_progress()
        self._set_state(JobState.COMPLETED)
        result = DownloadResult(final, self.downloaded, self._hasher.hexdigest())
        self._sink(Finished(self.job_id, result.path, result.size, result.sha256))
        return result

    # --- helpers ---------------------------------------------------------------------------

    def _emit_progress(self) -> None:
        speed = self._meter.speed()
        eta = eta_seconds(self.total, self.downloaded, speed)
        self._sink(Progress(self.job_id, self.downloaded, self.total, speed, eta))

    def _set_state(self, state: JobState, message: str = "") -> None:
        self.state = state
        self._sink(StateChanged(self.job_id, state, message))

    def _fail(self, error: DownloadError) -> None:
        self._set_state(JobState.FAILED, error.message)
        part = self.part_path
        self._sink(Failed(self.job_id, error, part if part and part.exists() else None))

    def _discard_partial(self) -> None:
        part = self.part_path
        if part is not None:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
