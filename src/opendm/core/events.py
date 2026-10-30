"""Events emitted by engines. Consumers must not block: the GUI bridge (M4) will
forward them across threads, the CLI renders them directly."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opendm.core.errors import DownloadError
from opendm.core.models import AfterAction, JobState


@dataclass(frozen=True, slots=True)
class Progress:
    job_id: str
    downloaded: int
    total: int | None
    speed: float  # bytes per second, averaged
    eta: float | None  # seconds
    connections: int = 0  # active connections
    segments: tuple[tuple[int, int | None, int], ...] = ()  # (start, end, received) for the map


@dataclass(frozen=True, slots=True)
class StateChanged:
    job_id: str
    state: JobState
    message: str = ""


@dataclass(frozen=True, slots=True)
class Finished:
    job_id: str
    path: Path
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Failed:
    job_id: str
    error: DownloadError
    partial_path: Path | None


@dataclass(frozen=True, slots=True)
class JobChanged:
    """The stored job changed (added, updated or removed); reload it."""

    job_id: str
    removed: bool = False


@dataclass(frozen=True, slots=True)
class QueueFinished:
    """A queue ran out of work after running at least one job."""

    queue_id: int
    name: str
    action: AfterAction


Event = Progress | StateChanged | Finished | Failed | JobChanged | QueueFinished
EventSink = Callable[[Event], None]


def discard(_event: Event) -> None:
    """An EventSink that ignores everything."""
