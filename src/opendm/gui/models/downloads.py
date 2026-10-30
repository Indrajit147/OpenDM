"""Table model of downloads, fed by job snapshots and live progress."""

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from opendm.core.events import Progress
from opendm.core.models import Job, JobState
from opendm.core.units import format_bytes, format_duration

NAME, SIZE, PROGRESS, SPEED, ETA, STATUS, ADDED = range(7)
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 2  # float 0..1, or -1 when unknown
JOB_ROLE = Qt.ItemDataRole.UserRole + 3
LIVE_STATES = frozenset({JobState.PROBING, JobState.DOWNLOADING, JobState.VERIFYING})
_Index = QModelIndex | QPersistentModelIndex


def tr(text: str) -> str:
    return QCoreApplication.translate("DownloadsModel", text)


def status_text(job: Job) -> str:
    labels = {
        JobState.QUEUED: tr("Queued"),
        JobState.PROBING: tr("Connecting"),
        JobState.DOWNLOADING: tr("Downloading"),
        JobState.VERIFYING: tr("Verifying"),
        JobState.PAUSED: tr("Paused"),
        JobState.COMPLETED: tr("Completed"),
        JobState.FAILED: tr("Failed"),
        JobState.CANCELLED: tr("Cancelled"),
    }
    text = labels[job.state]
    if job.state is JobState.FAILED and job.error_message:
        return f"{text}: {job.error_message}"
    if job.message and job.state in (JobState.PAUSED, JobState.QUEUED):
        return f"{text} ({job.message})"
    return text


@dataclass
class Row:
    job: Job
    speed: float = 0.0
    eta: float | None = None

    @property
    def fraction(self) -> float:
        if self.job.state is JobState.COMPLETED:
            return 1.0
        if not self.job.size:
            return -1.0
        return min(self.job.downloaded / self.job.size, 1.0)


class DownloadsModel(QAbstractTableModel):
    HEADERS = ("Name", "Size", "Progress", "Speed", "Time left", "Status", "Added")

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[Row] = []
        self._index: dict[str, int] = {}
        self.progress_updates = 0  # for the smoothness test

    # --- Qt API ---------------------------------------------------------------------------------

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self.HEADERS[section])
        return None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        job, col = row.job, index.column()
        if role == JOB_ROLE:
            return job
        if role == PROGRESS_ROLE:
            return row.fraction
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, col)
        if role == SORT_ROLE:
            return self._sort_key(row, col)
        if role == Qt.ItemDataRole.ToolTipRole and col in (NAME, STATUS):
            return f"{job.name}\n{status_text(job)}"
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (SIZE, SPEED, ETA):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def _display(self, row: Row, col: int) -> str:
        job = row.job
        live = job.state in LIVE_STATES
        if col == NAME:
            return job.name
        if col == SIZE:
            return format_bytes(job.size) if job.size is not None else "?"
        if col == PROGRESS:
            return "" if row.fraction < 0 else f"{row.fraction * 100:.1f}%"
        if col == SPEED:
            return f"{format_bytes(row.speed)}/s" if live and row.speed > 0 else ""
        if col == ETA:
            return format_duration(row.eta) if live and row.eta is not None else ""
        if col == STATUS:
            return status_text(job)
        local = job.created_at.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")

    def _sort_key(self, row: Row, col: int) -> Any:
        job = row.job
        keys: dict[int, Any] = {
            NAME: job.name.lower(),
            SIZE: job.size or 0,
            PROGRESS: row.fraction,
            SPEED: row.speed,
            ETA: row.eta if row.eta is not None else float("inf"),
            STATUS: str(job.state),
            ADDED: job.created_at.timestamp(),
        }
        return keys[col]

    # --- updates ----------------------------------------------------------------------------------

    def set_jobs(self, jobs: list[Job]) -> None:
        self.beginResetModel()
        self._rows = [Row(j) for j in jobs]
        self._reindex()
        self.endResetModel()

    def update_job(self, job: Job) -> None:
        position = self._index.get(job.id)
        if position is None:
            self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
            self._rows.append(Row(job))
            self._index[job.id] = len(self._rows) - 1
            self.endInsertRows()
            return
        row = self._rows[position]
        if job.state not in LIVE_STATES:
            row.speed, row.eta = 0.0, None
        if job.state is not JobState.COMPLETED and job.downloaded < row.job.downloaded:
            job.downloaded = row.job.downloaded  # snapshots lag behind live progress
        row.job = job
        self._changed(position, NAME, ADDED)

    def remove_job(self, job_id: str) -> None:
        position = self._index.get(job_id)
        if position is None:
            return
        self.beginRemoveRows(QModelIndex(), position, position)
        del self._rows[position]
        self._reindex()
        self.endRemoveRows()

    def update_progress(self, event: Progress) -> None:
        position = self._index.get(event.job_id)
        if position is None:
            return
        row = self._rows[position]
        row.job.downloaded = event.downloaded
        if event.total is not None:
            row.job.size = event.total
        row.speed, row.eta = event.speed, event.eta
        self.progress_updates += 1
        self._changed(position, SIZE, ETA)

    def job(self, job_id: str) -> Job | None:
        position = self._index.get(job_id)
        return None if position is None else self._rows[position].job

    def jobs(self) -> list[Job]:
        return [r.job for r in self._rows]

    def total_speed(self) -> float:
        return sum(r.speed for r in self._rows if r.job.state in LIVE_STATES)

    def _changed(self, position: int, first: int, last: int) -> None:
        self.dataChanged.emit(self.index(position, first), self.index(position, last))

    def _reindex(self) -> None:
        self._index = {r.job.id: i for i, r in enumerate(self._rows)}


class DownloadsFilter(QSortFilterProxyModel):
    """Sidebar views (all, unfinished, finished, a category, a queue) plus text search."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self._view: tuple[str, int | None] = ("all", None)
        self._search = ""

    def set_view(self, kind: str, value: int | None = None) -> None:
        self.beginFilterChange()
        self._view = (kind, value)
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_search(self, text: str) -> None:
        self.beginFilterChange()
        self._search = text.strip().lower()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: _Index) -> bool:
        model = self.sourceModel()
        job: Job = model.data(model.index(source_row, 0, source_parent), JOB_ROLE)
        kind, value = self._view
        visible = {
            "all": True,
            "unfinished": job.state is not JobState.COMPLETED,
            "finished": job.state is JobState.COMPLETED,
            "category": job.category_id == value,
            "queue": job.queue_id == value,
        }.get(kind, True)
        if visible and self._search:
            visible = self._search in job.name.lower() or self._search in job.request.url.lower()
        return visible
