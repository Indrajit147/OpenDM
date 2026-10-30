"""One OpenDM app per user session.

Windows: a named mutex in the session namespace (``Local\\...``); the OS releases it
when the process dies. Elsewhere: an exclusive lock on a file in the temp folder.
(A named pipe alone is not enough: Windows lets several servers share a pipe name.)
"""

import contextlib
import sys
import tempfile
from pathlib import Path
from typing import Any

_ERROR_ALREADY_EXISTS = 183


class InstanceLock:
    def __init__(self, name: str) -> None:
        self.name = name
        self._handle: Any = None

    def acquire(self) -> bool:
        """True if this process is now the only instance."""
        if self._handle is not None:
            return True
        if sys.platform == "win32":
            return self._acquire_windows()
        return self._acquire_file()

    def _acquire_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, f"Local\\{self.name}")
        if not handle:
            return False
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            return False
        self._handle = handle
        return True

    def _acquire_file(self) -> bool:
        import fcntl

        f = open(Path(tempfile.gettempdir()) / f"{self.name}.lock", "a")  # noqa: SIM115
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._handle = f
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(self._handle))
        else:
            with contextlib.suppress(OSError):
                self._handle.close()
        self._handle = None
