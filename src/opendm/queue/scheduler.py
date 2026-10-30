"""DownloadManager: jobs, queues, host limits and schedules on top of the engine.

Runs on one asyncio loop (the engine thread from M4 on) and owns the database
connection. Every change to a stored job is announced with a ``JobChanged`` event;
engine events are forwarded unchanged.
"""

import asyncio
import contextlib
import dataclasses
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from opendm.core.branding import PARTIAL_SUFFIX
from opendm.core.errors import DownloadError
from opendm.core.events import (
    Event,
    EventSink,
    JobChanged,
    Progress,
    QueueFinished,
    StateChanged,
    ToolProgress,
    discard,
)
from opendm.core.models import (
    MAIN_QUEUE_ID,
    AfterAction,
    Category,
    DownloadRequest,
    Job,
    JobState,
    ProbeResult,
    utc_now,
)
from opendm.core.settings import EngineSettings
from opendm.discovery.categories import category_folder, match_category
from opendm.engine.http.download import HttpDownload
from opendm.engine.http.naming import filename_from_url
from opendm.engine.http.probe import probe as probe_url
from opendm.engine.http.ratelimit import TokenBucket
from opendm.engine.http.transport import HttpxTransport
from opendm.engine.media.download import MediaDownload
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import MediaInfo, ToolPaths, analyze
from opendm.queue.host_limits import HostLimiter, host_of
from opendm.queue.power import NoPowerActions, PowerActions
from opendm.queue.schedule import in_window
from opendm.storage.db import Database
from opendm.storage.repositories import (
    CategoryRepository,
    JobRepository,
    QueueRepository,
    SettingsRepository,
)
from opendm.tools.manager import ToolInfo, ToolManager

StopReason = Literal["user", "queue", "shutdown", "remove"]
_LIVE_STATES = frozenset({JobState.PROBING, JobState.DOWNLOADING, JobState.VERIFYING})


AnyDownload = HttpDownload | MediaDownload


@dataclass
class _Run:
    download: AnyDownload
    task: "asyncio.Task[None]"
    host: str
    connections: int
    queue_id: int
    manual: bool
    reason: StopReason | None = None
    last_saved: float = field(default=0.0)


class DownloadManager:
    def __init__(
        self,
        db: Database,
        *,
        settings: EngineSettings | None = None,
        sink: EventSink = discard,
        per_host: int = 8,
        power: PowerActions | None = None,
        now: Callable[[], datetime] = datetime.now,
        save_interval: float = 2.0,
        temp_dir: Path | None = None,
    ) -> None:
        self.db = db
        self.temp_dir = temp_dir or Path(tempfile.gettempdir())  # cookie files for yt-dlp
        self.tools = ToolPaths()
        self.tool_manager: ToolManager | None = None
        self.jobs = JobRepository(db)
        self.queues = QueueRepository(db)
        self.categories = CategoryRepository(db)
        self.settings_store = SettingsRepository(db)
        self.settings = settings or EngineSettings()
        self.global_limiter = TokenBucket(None)
        self.hosts = HostLimiter(per_host)
        self._sink = sink
        self._power = power or NoPowerActions()
        self._now = now
        self._save_interval = save_interval
        self._running: dict[str, _Run] = {}
        self._manual: set[str] = set()  # started by the user, regardless of queue state
        self._restart: set[str] = set()
        self._active_queues: set[int] = set()
        self._ran: dict[int, bool] = {}  # queue ran a job during this activation
        self._windows: dict[int, bool] = {}
        self._background: set[asyncio.Task[None]] = set()

    # --- lifecycle -------------------------------------------------------------------------------

    async def open(self) -> int:
        """Recover after a crash; returns how many jobs were marked interrupted."""
        count = self.jobs.mark_interrupted()
        await self.tick()
        return count

    async def close(self) -> None:
        """Pause everything (checkpoints are saved) before the app exits."""
        for run in list(self._running.values()):
            run.reason = "shutdown"
            run.download.pause()
        await self._wait_tasks([r.task for r in self._running.values()])
        for task in list(self._background):
            task.cancel()

    async def wait_idle(self) -> None:
        """Return once nothing is running and nothing more can start."""
        while self._running:
            await self._wait_tasks([r.task for r in self._running.values()], first=True)
            await asyncio.sleep(0)

    async def run_scheduler(self, interval: float = 30.0) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(interval)

    # --- jobs -------------------------------------------------------------------------------------

    def suggest_target(self, filename: str, base_dir: Path) -> tuple[Category, Path]:
        """Category and folder for a file name (for the download-start dialog)."""
        category = match_category(filename, self.categories.list())
        return category, category_folder(category, base_dir)

    async def add(
        self,
        request: DownloadRequest,
        *,
        queue_id: int = MAIN_QUEUE_ID,
        start: bool = True,
        category_id: int | None = None,
        connections: int | None = None,
    ) -> Job:
        if category_id is None:
            name = request.filename or filename_from_url(request.url) or ""
            category_id = match_category(name, self.categories.list()).id
        job = self.jobs.add(
            Job(request, queue_id=queue_id, category_id=category_id, connections=connections)
        )
        self._emit(JobChanged(job.id))
        if start:
            self._manual.add(job.id)
        self._pump()
        return job

    def set_tools(self, tools: ToolPaths) -> None:
        """yt-dlp/FFmpeg locations for media jobs started from now on."""
        self.tools = tools

    def configure_tools(self, folder: Path, overrides: dict[str, Path]) -> ToolManager:
        self.tool_manager = ToolManager(folder, overrides=overrides)
        self.set_tools(self.tool_manager.paths())
        return self.tool_manager

    async def tool_status(self) -> list[ToolInfo]:
        return await self._tools_or_default().status()

    async def install_tool(self, name: str) -> ToolInfo:
        """Install or update yt-dlp or ffmpeg (the caller has the user's consent)."""
        tools = self._tools_or_default()

        def report(done: int, total: int | None) -> None:
            self._emit(ToolProgress(name, done, total))

        if name == "yt-dlp":
            info = await tools.install_ytdlp(report)
        elif name == "ffmpeg":
            info = await tools.install_ffmpeg(report)
        else:
            raise ValueError(f"unknown tool {name}")
        self.set_tools(tools.paths())
        return info

    async def use_existing_tool(self, name: str, path: Path) -> ToolInfo:
        tools = self._tools_or_default()
        info = await tools.use_existing(name, path)
        self.set_tools(tools.paths())
        return info

    async def check_ytdlp_update(self) -> tuple[str | None, str] | None:
        """(installed, latest) when a newer yt-dlp exists, else None."""
        return await self._tools_or_default().ytdlp_update_available()

    async def tool_downloads(self) -> dict[str, int | None]:
        """Download sizes for the consent dialog (None if unknown)."""
        tools = self._tools_or_default()
        sizes: dict[str, int | None] = {}
        for name, fetch in (("yt-dlp", tools.latest_ytdlp), ("ffmpeg", tools.ffmpeg_release)):
            try:
                sizes[name] = (await fetch()).size
            except DownloadError:
                sizes[name] = None
        return sizes

    def _tools_or_default(self) -> ToolManager:
        if self.tool_manager is None:
            self.tool_manager = ToolManager(self.temp_dir / "tools")
        return self.tool_manager

    async def analyze_media(self, request: DownloadRequest) -> MediaInfo:
        """What yt-dlp finds on a page (title, qualities, subtitles, playlist entries)."""
        return await analyze(
            self.tools,
            request,
            temp_dir=self.temp_dir,
            proxy=self.settings.proxy,
            use_system_proxy=self.settings.use_system_proxy,
        )

    async def add_media(
        self,
        request: DownloadRequest,
        options: MediaOptions,
        *,
        queue_id: int = MAIN_QUEUE_ID,
        start: bool = True,
        category_id: int | None = None,
    ) -> Job:
        if category_id is None:
            name = "x.mp3" if options.audio_only else "x." + options.container
            category_id = match_category(name, self.categories.list()).id
        job = self.jobs.add(
            Job(request, queue_id=queue_id, category_id=category_id,
                media_options=options.to_dict())
        )  # fmt: skip
        self._emit(JobChanged(job.id))
        if start:
            self._manual.add(job.id)
        self._pump()
        return job

    async def start(self, job_id: str) -> None:
        """Start or resume a job now, whatever its queue is doing."""
        job = self._require(job_id)
        if job_id in self._running or job.state is JobState.COMPLETED:
            return
        self._set(job, JobState.QUEUED, "")
        self._manual.add(job_id)
        self._pump()

    async def restart(self, job_id: str) -> None:
        """Start over from zero (e.g. after the file changed on the server)."""
        self._restart.add(job_id)
        await self.start(job_id)

    async def pause(self, job_id: str) -> None:
        self._manual.discard(job_id)
        if await self._stop(job_id, "user"):
            return
        job = self.jobs.get(job_id)
        if job is not None and job.state is JobState.QUEUED:
            self._set(job, JobState.PAUSED, "")

    async def remove(self, job_id: str, *, delete_file: bool = False) -> None:
        """Remove a job; ``delete_file`` also deletes its file (ask the user first)."""
        self._manual.discard(job_id)
        await self._stop(job_id, "remove")
        if self.jobs.delete(job_id, delete_file=delete_file):
            self._emit(JobChanged(job_id, removed=True))
        self._pump()

    async def refresh_link(
        self, job_id: str, url: str, headers: dict[str, str] | None = None
    ) -> None:
        """Point a stopped job at a new link; the engine checks it is the same file."""
        await self._stop(job_id, "user")
        job = self._require(job_id)
        changes: dict[str, object] = {"url": url}
        if headers is not None:
            changes["headers"] = headers
        job.request = dataclasses.replace(job.request, **changes)  # type: ignore[arg-type]
        job.relinked = job.final_path is not None
        self.jobs.save(job)
        self._emit(JobChanged(job_id))

    async def redownload(self, job_id: str, *, start: bool = True) -> Job:
        job = self.jobs.redownload(job_id)
        self._emit(JobChanged(job.id))
        if start:
            self._manual.add(job.id)
        self._pump()
        return job

    async def move_to_queue(self, job_id: str, queue_id: int) -> None:
        job = self._require(job_id)
        if job.queue_id == queue_id:
            return
        job.queue_id = queue_id
        job.position = self.jobs.next_position(queue_id)
        self.jobs.save(job)
        self._emit(JobChanged(job_id))
        self._pump()

    async def pause_all(self) -> None:
        for job_id in list(self._running):
            await self.pause(job_id)

    def set_global_speed_limit(self, rate: int | None) -> None:
        self.global_limiter.rate = rate

    def apply_settings(self, settings: EngineSettings, global_limit: int | None) -> None:
        """User-facing engine options; applies to downloads started from now on."""
        self.settings = dataclasses.replace(
            self.settings,
            connections=settings.connections,
            per_host_limit=settings.per_host_limit,
            proxy=settings.proxy,
            use_system_proxy=settings.use_system_proxy,
        )
        self.hosts.per_host = settings.per_host_limit
        self.set_global_speed_limit(global_limit)

    async def probe(self, request: DownloadRequest) -> ProbeResult:
        """Probe a URL with the current proxy settings (for the start dialog)."""
        transport = HttpxTransport(
            verify=request.verify_tls,
            proxy=self.settings.proxy,
            use_system_proxy=self.settings.use_system_proxy,
        )
        try:
            return await probe_url(transport, request.url, request.request_headers())
        finally:
            await transport.aclose()

    # --- queues -----------------------------------------------------------------------------------

    async def start_queue(self, queue_id: int) -> None:
        self._active_queues.add(queue_id)
        self._ran[queue_id] = False
        self._pump()

    async def stop_queue(self, queue_id: int) -> None:
        """Stop a queue: its running jobs go back to waiting (not 'paused by user')."""
        self._active_queues.discard(queue_id)
        for job_id, run in list(self._running.items()):
            if run.queue_id == queue_id and not run.manual:
                await self._stop(job_id, "queue")

    async def tick(self) -> None:
        """Apply queue schedules: start on entering a window, stop on leaving it."""
        now = self._now()
        for queue in self.queues.list():
            assert queue.id is not None
            inside = in_window(queue, now)
            before = self._windows.get(queue.id)
            self._windows[queue.id] = inside
            if inside and not before:
                await self.start_queue(queue.id)
            elif before and not inside and queue.stop_time:
                await self.stop_queue(queue.id)

    # --- scheduling -------------------------------------------------------------------------------

    def _pump(self) -> None:
        """Start every job that may run now, in queue order."""
        queues = {q.id: q for q in self.queues.list()}
        busy: dict[int, int] = {}
        for run in self._running.values():
            busy[run.queue_id] = busy.get(run.queue_id, 0) + 1
        for job in self.jobs.list(states={JobState.QUEUED}):
            if job.id in self._running:
                continue
            manual = job.id in self._manual
            queue = queues.get(job.queue_id)
            if not manual:
                if job.queue_id not in self._active_queues or queue is None:
                    continue
                if busy.get(job.queue_id, 0) >= queue.max_concurrent:
                    continue
            host = host_of(job.request.url)
            wanted = min(
                job.connections or self.settings.connections,
                self.settings.effective_connections(),
            )
            granted = self.hosts.acquire(host, wanted)
            if granted == 0:
                continue
            self._launch(job, host, granted, manual)
            busy[job.queue_id] = busy.get(job.queue_id, 0) + 1
        self._check_finished_queues()

    def _launch(self, job: Job, host: str, connections: int, manual: bool) -> None:
        request = job.request
        if job.final_path is not None:
            request = dataclasses.replace(
                request, dest_dir=job.final_path.parent, filename=job.final_path.name
            )
            if job.relinked:
                part = job.final_path.with_name(job.final_path.name + PARTIAL_SUFFIX)
                request = dataclasses.replace(request, part_file=part)
        if job.id in self._restart:
            self._restart.discard(job.id)
            request = dataclasses.replace(request, restart=True, part_file=None)
        settings = dataclasses.replace(self.settings, connections=connections)
        sink = self._job_sink(job.id)
        download: AnyDownload
        if job.media_options is not None:
            # yt-dlp picks the file name itself; keep the user's choice only if they made one.
            media_request = dataclasses.replace(
                job.request, dest_dir=request.dest_dir, part_file=None, restart=False
            )
            download = MediaDownload(
                media_request,
                MediaOptions.from_dict(job.media_options),
                tools=self.tools,
                temp_dir=self.temp_dir,
                settings=settings,
                sink=sink,
                job_id=job.id,
            )
        else:
            download = HttpDownload(
                request,
                settings=settings,
                sink=sink,
                global_limiter=self.global_limiter,
                job_id=job.id,
            )
        self._manual.discard(job.id)
        job.started_at = utc_now()
        job.error_kind = job.error_message = None
        self._set(job, JobState.PROBING, "")
        if job.queue_id in self._active_queues:
            self._ran[job.queue_id] = True
        task = asyncio.create_task(self._drive(job.id, download))
        self._running[job.id] = _Run(download, task, host, connections, job.queue_id, manual)

    def _job_sink(self, job_id: str) -> Callable[[Event], None]:
        return lambda event: self._on_event(job_id, event)

    async def _drive(self, job_id: str, download: "AnyDownload") -> None:
        error: DownloadError | None = None
        result = None
        try:
            result = await download.run()
        except DownloadError as exc:
            error = exc
        except asyncio.CancelledError:
            self._finish_run(job_id, download, None, None, cancelled=True)
            raise
        self._finish_run(job_id, download, result, error)

    def _finish_run(
        self,
        job_id: str,
        download: HttpDownload,
        result: object,
        error: DownloadError | None,
        cancelled: bool = False,
    ) -> None:
        run = self._running.pop(job_id)
        self.hosts.release(run.host, run.connections)
        job = self.jobs.get(job_id)
        if job is not None and run.reason != "remove":
            if download.final_path is not None:
                job.final_path = download.final_path
            job.size = download.total
            job.downloaded = download.downloaded
            if error is not None:
                job.state, job.message = JobState.FAILED, error.message
                job.error_kind, job.error_message = str(error.kind), error.message
            elif result is not None:
                job.state, job.message = JobState.COMPLETED, ""
                job.sha256 = getattr(result, "sha256", None)
                job.downloaded = job.size or job.downloaded
                job.completed_at = utc_now()
                job.relinked = False
            elif run.reason == "queue":
                job.state, job.message = JobState.QUEUED, "stopped by schedule"
            elif run.reason == "shutdown" or cancelled:
                job.state, job.message = JobState.PAUSED, "interrupted"
            else:
                job.state, job.message = JobState.PAUSED, ""
            self.jobs.save(job)
            self._emit(JobChanged(job_id))
        if not cancelled:
            self._pump()

    def _check_finished_queues(self) -> None:
        for queue_id in list(self._active_queues):
            if any(r.queue_id == queue_id for r in self._running.values()):
                continue
            if self.jobs.list(states={JobState.QUEUED}, queue_id=queue_id, limit=1):
                continue  # still waiting, e.g. for a host connection
            self._active_queues.discard(queue_id)
            if not self._ran.pop(queue_id, False):
                continue  # nothing ran: never sleep or shut down for an empty queue
            queue = self.queues.get(queue_id)
            if queue is None:
                continue
            self._emit(QueueFinished(queue_id, queue.name, queue.after_action))
            if queue.after_action is not AfterAction.NONE:
                task = asyncio.create_task(self._power.perform(queue.after_action, queue))
                self._background.add(task)
                task.add_done_callback(self._background.discard)

    # --- engine events ----------------------------------------------------------------------------

    def _on_event(self, job_id: str, event: Event) -> None:
        run = self._running.get(job_id)
        if run is not None:
            if isinstance(event, StateChanged) and event.state in _LIVE_STATES:
                job = self.jobs.get(job_id)
                if job is not None and (
                    job.state is not event.state or job.final_path != run.download.final_path
                ):
                    job.state = event.state
                    job.final_path = run.download.final_path or job.final_path
                    job.size = run.download.total
                    self.jobs.save(job)
                    self._emit(JobChanged(job_id))
            elif isinstance(event, Progress):
                now = time.monotonic()
                if now - run.last_saved >= self._save_interval:
                    run.last_saved = now
                    self.jobs.update_progress(job_id, event.downloaded, event.total)
        self._emit(event)

    # --- helpers ----------------------------------------------------------------------------------

    async def _stop(self, job_id: str, reason: StopReason) -> bool:
        """Pause a running job (keeping its files); False if it was not running."""
        run = self._running.get(job_id)
        if run is None:
            return False
        run.reason = reason
        run.download.pause()
        await self._wait_tasks([run.task])
        return True

    @staticmethod
    async def _wait_tasks(tasks: list["asyncio.Task[None]"], first: bool = False) -> None:
        if not tasks:
            return
        mode = asyncio.FIRST_COMPLETED if first else asyncio.ALL_COMPLETED
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait(tasks, return_when=mode)

    def _require(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _set(self, job: Job, state: JobState, message: str) -> None:
        job.state, job.message = state, message
        self.jobs.save(job)
        self._emit(JobChanged(job.id))

    def _emit(self, event: Event) -> None:
        self._sink(event)
