"""The preallocated ``.odm-part`` file with positioned writes (decision D8).

Methods block; the engine calls them through ``asyncio.to_thread``. A lock keeps
seek+write pairs atomic, since Windows has no ``os.pwrite``.
"""

import os
import threading
from pathlib import Path

_FLAGS = os.O_RDWR | getattr(os, "O_BINARY", 0)


class PartFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self, *, create: bool) -> None:
        flags = _FLAGS | (os.O_CREAT if create else 0)
        self._fd = os.open(self.path, flags, 0o644)

    def _require(self) -> int:
        if self._fd is None:
            raise RuntimeError("part file is not open")
        return self._fd

    def preallocate(self, size: int) -> None:
        """Set the file length; on NTFS this reserves the clusters up front."""
        with self._lock:
            os.ftruncate(self._require(), size)

    def truncate(self, size: int) -> None:
        self.preallocate(size)

    def write_at(self, offset: int, data: bytes) -> None:
        with self._lock:
            fd = self._require()
            os.lseek(fd, offset, os.SEEK_SET)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]

    def sync(self) -> None:
        with self._lock:
            os.fsync(self._require())

    def close(self) -> None:
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
