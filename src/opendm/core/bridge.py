"""Engine <-> GUI bridge (decision D2). No Qt here.

``EngineThread`` runs the asyncio loop, the database and the ``DownloadManager`` on
one background thread. The GUI sends work with ``call()`` (returns a
``concurrent.futures.Future``) and collects events with ``drain()``. Whenever a job
changes, the engine thread attaches a ``JobSnapshot`` so the GUI never reads SQLite.
"""

import asyncio
import concurrent.futures
import inspect
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from opendm.core.events import Event, JobChanged, JobSnapshot, PowerRequested, Progress
from opendm.core.models import AfterAction, Queue
from opendm.core.settings import EngineSettings
from opendm.queue.scheduler import DownloadManager
from opendm.storage.db import Database

T = TypeVar("T")
THREAD_NAME = "opendm-engine"


def coalesce(events: list[Event]) -> list[Event]:
    """Keep only the newest Progress per job (at its last position); keep everything else."""
    last = {e.job_id: i for i, e in enumerate(events) if isinstance(e, Progress)}
    return [e for i, e in enumerate(events) if not isinstance(e, Progress) or last[e.job_id] == i]


class _EventPower:
    """After-queue actions become events; the GUI shows the countdown and acts."""

    def __init__(self, put: Callable[[Event], None]) -> None:
        self._put = put

    async def perform(self, action: AfterAction, queue: Queue) -> None:
        self._put(PowerRequested(action, queue.name))


class EngineThread:
    def __init__(
        self,
        db_path: Path | str,
        *,
        settings: EngineSettings | None = None,
        per_host: int = 8,
        scheduler_interval: float = 30.0,
    ) -> None:
        self._db_path = db_path
        self._settings = settings
        self._per_host = per_host
        self._interval = scheduler_interval
        self._events: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.manager: DownloadManager | None = None
        self._stopping = False

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self, timeout: float = 30) -> None:
        self.thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self.thread.start()
        self._ready.wait(timeout)
        if self._error is not None:
            raise self._error
        if not self._ready.is_set():
            raise TimeoutError("engine thread did not start")

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        db: Database | None = None
        try:
            db = Database(self._db_path)
            self.manager = DownloadManager(
                db,
                settings=self._settings,
                sink=self._on_event,
                per_host=self._per_host,
                power=_EventPower(self._events.put),
            )
            loop.run_until_complete(self.manager.open())
            scheduler = loop.create_task(self.manager.run_scheduler(self._interval))
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            if db is not None:
                db.close()
            loop.close()
            return
        self.loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            scheduler.cancel()
            loop.run_until_complete(self.manager.close())
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            db.close()
            loop.close()

    def stop(self, timeout: float = 30) -> None:
        """Pause running downloads (checkpointing them) and end the thread."""
        self._stopping = True
        if self.loop is not None and self.thread is not None and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout)

    # --- commands and events -----------------------------------------------------------------

    def call(self, fn: Callable[[DownloadManager], Any]) -> "concurrent.futures.Future[Any]":
        """Run ``fn(manager)`` on the engine thread; awaits it if it returns a coroutine."""
        if self.loop is None or self.manager is None or self._stopping:
            raise RuntimeError("the engine is not running")
        manager = self.manager

        async def runner() -> Any:
            result = fn(manager)
            if inspect.isawaitable(result):
                result = await result
            return result

        return asyncio.run_coroutine_threadsafe(runner(), self.loop)

    def drain(self) -> list[Event]:
        """All events since the last call, with progress merged per job."""
        events: list[Event] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return coalesce(events)

    def _on_event(self, event: Event) -> None:
        """Runs on the engine thread."""
        if isinstance(event, JobChanged):
            assert self.manager is not None
            job = None if event.removed else self.manager.jobs.get(event.job_id)
            self._events.put(JobSnapshot(event.job_id, job))
            return
        self._events.put(event)
