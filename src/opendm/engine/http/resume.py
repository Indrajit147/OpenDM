"""Crash-safe resume: the ``.odm-state`` sidecar and the ``.odm-lock`` file.

The sidecar never holds cookies, headers or the URL itself (URLs often carry
tokens); a SHA-256 of the request URL identifies the download instead.
Writers must fsync the data file *before* saving a state that claims those bytes.
"""

import contextlib
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.models import ProbeResult

STATE_VERSION = 1

SegmentTuple = tuple[int, int | None, int]  # start, end (exclusive), bytes written


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DownloadState:
    url_hash: str
    size: int | None
    etag: str | None
    last_modified: str | None
    accepts_ranges: bool
    segments: tuple[SegmentTuple, ...]

    @classmethod
    def from_probe(cls, probe: ProbeResult, segments: list[SegmentTuple]) -> "DownloadState":
        return cls(
            url_hash=url_hash(probe.url),
            size=probe.size,
            etag=probe.etag,
            last_modified=probe.last_modified,
            accepts_ranges=probe.accepts_ranges,
            segments=tuple(segments),
        )

    @property
    def written(self) -> int:
        return sum(w for _, _, w in self.segments)


def save_state(path: Path, state: DownloadState) -> None:
    """Write atomically: temp file, fsync, then rename over the old state."""
    data = asdict(state) | {"version": STATE_VERSION}
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _valid_segments(raw: Any, size: Any) -> tuple[SegmentTuple, ...] | None:
    if not isinstance(raw, list) or not raw:
        return None
    segments: list[SegmentTuple] = []
    expected_start = 0
    for item in raw:
        if not (isinstance(item, list) and len(item) == 3):
            return None
        start, end, written = item
        if not (isinstance(start, int) and isinstance(written, int) and start == expected_start):
            return None
        if end is None:
            if size is not None or len(raw) != 1:
                return None
        elif not isinstance(end, int) or end < start or not 0 <= written <= end - start:
            return None
        segments.append((start, end, written))
        expected_start = end if end is not None else start
    if size is not None and expected_start != size:
        return None
    return tuple(segments)


def load_state(path: Path) -> DownloadState | None:
    """Read a sidecar; None if missing, damaged or from another format version."""
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    try:
        size = data["size"]
        segments = _valid_segments(data["segments"], size)
        if segments is None or not (size is None or isinstance(size, int)):
            return None
        return DownloadState(
            url_hash=str(data["url_hash"]),
            size=size,
            etag=data["etag"],
            last_modified=data["last_modified"],
            accepts_ranges=bool(data["accepts_ranges"]),
            segments=segments,
        )
    except (KeyError, TypeError, ValueError):
        return None


def mismatch_reason(state: DownloadState, probe: ProbeResult) -> str | None:
    """Why the partial file cannot be continued from ``probe``; None if it can."""
    if state.size != probe.size:
        return f"size changed ({state.size} -> {probe.size} bytes)"
    if not probe.accepts_ranges:
        return "the server no longer supports resuming"
    if state.etag and probe.etag:
        return None if state.etag == probe.etag else "ETag changed"
    if state.last_modified and probe.last_modified:
        if state.last_modified == probe.last_modified:
            return None
        return "Last-Modified changed"
    return "the server sends no ETag or Last-Modified, so the partial file cannot be verified"


class FileLock:
    """Non-blocking OS lock so two processes never write the same partial file.

    The OS drops the lock when a process dies, so a leftover lock file is harmless.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        f = open(self.path, "a+b")  # noqa: SIM115  (held open until release)
        try:
            f.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            f.close()
            raise DownloadError(
                ErrorKind.IN_USE, f"another process is downloading {self.path.stem}"
            ) from exc
        self._file = f

    def release(self) -> None:
        if self._file is None:
            return
        with contextlib.suppress(OSError):
            if sys.platform == "win32":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        self._file.close()
        self._file = None
        with contextlib.suppress(OSError):
            self.path.unlink(missing_ok=True)
