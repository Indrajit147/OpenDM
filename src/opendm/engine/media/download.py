"""MediaDownload: a yt-dlp download with the same interface as HttpDownload.

Pause stops the process (and its FFmpeg children); resume runs yt-dlp again with
``--continue``. Partial files stay next to the target (spec 6.10). The final file's
SHA-256 is computed like for HTTP downloads.
"""

import asyncio
import contextlib
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from opendm.core.checksum import file_digest
from opendm.core.errors import DownloadError, ErrorKind, error_from_os
from opendm.core.events import EventSink, Failed, Finished, Progress, StateChanged, discard
from opendm.core.filenames import sanitize_filename
from opendm.core.models import DownloadRequest, DownloadResult, JobState
from opendm.core.progress import Clock, Throttle
from opendm.core.settings import EngineSettings
from opendm.engine.media.cookies import temporary_cookie_file
from opendm.engine.media.formats import MediaOptions, ytdlp_format_args
from opendm.engine.media.process import ToolProcess
from opendm.engine.media.progress import (
    FILE_TEMPLATE,
    PLANNED_TEMPLATE,
    PROGRESS_TEMPLATE,
    ProgressTracker,
    classify_ytdlp_error,
    parse_line,
)
from opendm.engine.media.ytdlp import (
    ToolPaths,
    check_manifest,
    looks_like_manifest,
    request_args,
)

_FINAL_STATES = frozenset({JobState.COMPLETED, JobState.CANCELLED})
_LEFTOVER_SUFFIXES = (".part", ".ytdl", ".temp")
DEFAULT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"


class MediaDownload:
    def __init__(
        self,
        request: DownloadRequest,
        options: MediaOptions,
        *,
        tools: ToolPaths,
        temp_dir: Path,
        settings: EngineSettings | None = None,
        sink: EventSink = discard,
        job_id: str | None = None,
        clock: Clock = time.monotonic,
    ) -> None:
        self.request = request
        self.options = options
        self.tools = tools
        self.settings = settings or EngineSettings()
        self.job_id = job_id or uuid.uuid4().hex[:12]
        self.state = JobState.QUEUED
        self.final_path: Path | None = None
        self.planned_path: Path | None = None
        self.total: int | None = None
        self.downloaded = 0
        self._temp_dir = temp_dir
        self._sink = sink
        self._throttle = Throttle(self.settings.progress_interval, clock=clock)
        self._tracker = ProgressTracker()
        self._speed = 0.0
        self._eta: float | None = None
        self._task: asyncio.Task[Any] | None = None
        self._stop: Literal["pause", "cancel"] | None = None
        self._process: ToolProcess | None = None

    # --- control ------------------------------------------------------------------------------

    def pause(self) -> None:
        if self._task is not None and not self._task.done():
            self._stop = "pause"
            self._task.cancel()

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._stop = "cancel"
            self._task.cancel()
        elif self.state not in _FINAL_STATES:
            self._discard_partial()
            self._set_state(JobState.CANCELLED)

    def restart(self) -> None:
        if self._task is not None:
            raise RuntimeError("pause the download before restarting it")
        self._discard_partial()
        self._set_state(JobState.QUEUED, "restarting from the beginning")

    def set_speed_limit(self, rate: int | None) -> None:
        """Takes effect when the download is next started (yt-dlp reads it at launch)."""
        self.request = _replace(self.request, speed_limit=rate)

    # --- main flow ------------------------------------------------------------------------------

    async def run(self) -> DownloadResult | None:
        if self.state in _FINAL_STATES:
            raise RuntimeError(f"download already {self.state}")
        if self._task is not None:
            raise RuntimeError("download is already running")
        self._task = asyncio.current_task()
        self._stop = None
        try:
            self._set_state(JobState.PROBING)
            command = self.tools.ytdlp_command()
            if looks_like_manifest(self.request.url):
                await check_manifest(
                    self.request.url,
                    self.request,
                    proxy=self.settings.proxy,
                    use_system_proxy=self.settings.use_system_proxy,
                )
            if not self.tools.ffmpeg_available() and self._needs_ffmpeg():
                raise DownloadError(ErrorKind.TOOL_MISSING, "FFmpeg is not installed")
            try:
                self.request.dest_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise error_from_os(exc) from exc
            with temporary_cookie_file(self.request.cookies, self.request.url,
                                       self._temp_dir) as cookies:  # fmt: skip
                code, stderr = await self._run_process([*command, *self._args(cookies)])
            if code != 0:
                raise classify_ytdlp_error(stderr)
            return await self._finish()
        except asyncio.CancelledError:
            await self._stop_process()
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
            await self._stop_process()
            self._fail(exc)
            raise
        except Exception as exc:
            await self._stop_process()
            error = DownloadError(ErrorKind.UNKNOWN, f"unexpected error: {exc!r}")
            self._fail(error)
            raise error from exc
        finally:
            self._task = None

    def _needs_ffmpeg(self) -> bool:
        return True  # merging, audio extraction, remuxing and thumbnails all use FFmpeg

    def _args(self, cookie_file: Path | None) -> list[str]:
        settings = self.settings
        template = DEFAULT_TEMPLATE
        if self.request.filename:
            stem = sanitize_filename(Path(self.request.filename).stem, default="download")
            template = stem.replace("%", "%%") + ".%(ext)s"
        args = [
            "--newline", "--no-colors", "--encoding", "utf-8", "--progress", "--no-simulate",
            "--no-playlist", "--continue", "--no-mtime", "--windows-filenames",
            "--progress-template", PROGRESS_TEMPLATE,
            "--print", PLANNED_TEMPLATE, "--print", FILE_TEMPLATE,
            "-P", f"home:{self.request.dest_dir}", "-o", template,
            "--concurrent-fragments", str(max(1, settings.effective_connections())),
            "--retries", str(settings.retry.max_retries),
            "--fragment-retries", str(settings.retry.max_retries),
        ]  # fmt: skip
        if self.tools.ffmpeg is not None:
            args += ["--ffmpeg-location", str(self.tools.ffmpeg.parent)]
        if self.request.speed_limit:
            args += ["--limit-rate", str(self.request.speed_limit)]
        args += request_args(
            self.request,
            proxy=settings.proxy,
            use_system_proxy=settings.use_system_proxy,
            cookie_file=cookie_file,
        )
        args += ytdlp_format_args(self.options)
        return [*args, "--", self.request.url]

    async def _run_process(self, args: list[str]) -> tuple[int, str]:
        process = await ToolProcess.start(args, on_stderr=self._handle_line)
        self._process = process
        async for line in process.lines():
            self._handle_line(line)
        code = await process.wait()
        process.close()
        self._process = None
        return code, process.stderr

    def _handle_line(self, line: str) -> None:
        parsed = parse_line(line)
        if parsed is None:
            return
        kind, value = parsed
        if kind == "progress":
            if self.state is JobState.PROBING:
                self._set_state(JobState.DOWNLOADING)
            self._tracker.update(value)
            self.downloaded = self._tracker.downloaded
            self.total = self._tracker.total
            self._speed = value["speed"] or 0.0
            self._eta = value["eta"]
            if self._throttle.ready():
                self._emit_progress()
        elif kind == "planned":
            self.planned_path = Path(value)
        elif kind == "file":
            self.final_path = Path(value)
        elif kind == "phase":
            self._set_state(JobState.DOWNLOADING, "merging" if value == "merging" else "converting")

    async def _finish(self) -> DownloadResult:
        path = self.final_path
        if path is None or not path.is_file():
            raise DownloadError(ErrorKind.MEDIA, "yt-dlp finished but reported no file")
        self._set_state(JobState.VERIFYING)
        try:
            sha256 = await asyncio.to_thread(file_digest, path, "sha256")
            size = path.stat().st_size
        except OSError as exc:
            raise error_from_os(exc) from exc
        self.downloaded = self.total = size
        self._speed, self._eta = 0.0, 0.0
        self._emit_progress()
        self._set_state(JobState.COMPLETED)
        result = DownloadResult(path, size, sha256)
        self._sink(Finished(self.job_id, path, size, sha256))
        return result

    # --- helpers ---------------------------------------------------------------------------------

    async def _stop_process(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            await process.stop()

    def _discard_partial(self) -> None:
        """Remove yt-dlp's partial files for this download (never finished files)."""
        planned = self.planned_path
        if planned is None:
            return
        stem = planned.stem
        with contextlib.suppress(OSError):
            for leftover in planned.parent.iterdir():
                if leftover.name.startswith(stem) and leftover.name.endswith(_LEFTOVER_SUFFIXES):
                    leftover.unlink(missing_ok=True)

    def _emit_progress(self) -> None:
        self._sink(
            Progress(
                self.job_id, self.downloaded, self.total, self._speed, self._eta,
                1 if self.state is JobState.DOWNLOADING else 0, (),
            )
        )  # fmt: skip

    def _set_state(self, state: JobState, message: str = "") -> None:
        self.state = state
        self._sink(StateChanged(self.job_id, state, message))

    def _fail(self, error: DownloadError) -> None:
        self._set_state(JobState.FAILED, error.message)
        self._sink(Failed(self.job_id, error, None))


def _replace(request: DownloadRequest, **changes: Any) -> DownloadRequest:
    import dataclasses

    return dataclasses.replace(request, **changes)
