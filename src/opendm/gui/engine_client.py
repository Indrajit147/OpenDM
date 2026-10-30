"""Qt side of the engine bridge: turns drained engine events into Qt signals.

A timer empties the bridge's queue every 250 ms (progress is already merged per
job), so the GUI repaints at most ~4 times a second per download (spec 6.4).
"""

import concurrent.futures
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from opendm.core.bridge import EngineThread
from opendm.core.events import (
    Failed,
    Finished,
    JobSnapshot,
    PowerRequested,
    Progress,
    QueueFinished,
    StateChanged,
)
from opendm.queue.scheduler import DownloadManager

PUMP_INTERVAL_MS = 250


class EngineClient(QObject):
    jobUpdated = Signal(object)  # Job
    jobRemoved = Signal(str)  # job id
    progress = Signal(object)  # Progress
    stateChanged = Signal(object)  # StateChanged
    finished = Signal(object)  # Finished
    failed = Signal(object)  # Failed
    queueFinished = Signal(object)  # QueueFinished
    powerRequested = Signal(object)  # PowerRequested
    _done = Signal(object, object, object)  # callback, result, error

    def __init__(self, engine: EngineThread, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._done.connect(self._deliver)
        self._timer = QTimer(self)
        self._timer.setInterval(PUMP_INTERVAL_MS)
        self._timer.timeout.connect(self.pump)
        self._timer.start()

    def pump(self) -> None:
        for event in self.engine.drain():
            if isinstance(event, JobSnapshot):
                if event.job is None:
                    self.jobRemoved.emit(event.job_id)
                else:
                    self.jobUpdated.emit(event.job)
            elif isinstance(event, Progress):
                self.progress.emit(event)
            elif isinstance(event, StateChanged):
                self.stateChanged.emit(event)
            elif isinstance(event, Finished):
                self.finished.emit(event)
            elif isinstance(event, Failed):
                self.failed.emit(event)
            elif isinstance(event, QueueFinished):
                self.queueFinished.emit(event)
            elif isinstance(event, PowerRequested):
                self.powerRequested.emit(event)

    def call(
        self,
        fn: Callable[[DownloadManager], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> "concurrent.futures.Future[Any]":
        """Run ``fn(manager)`` on the engine thread; callbacks run on the GUI thread."""
        future = self.engine.call(fn)
        if on_done is not None or on_error is not None:

            def relay(f: "concurrent.futures.Future[Any]") -> None:
                error = f.exception()
                if error is None:
                    self._done.emit(on_done, f.result(), None)
                else:
                    self._done.emit(on_error, None, error)

            future.add_done_callback(relay)
        return future

    def _deliver(self, callback: Callable[[Any], None] | None, result: Any, error: Any) -> None:
        if callback is not None:
            callback(error if error is not None else result)

    def stop(self) -> None:
        self._timer.stop()
