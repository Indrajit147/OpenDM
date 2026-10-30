"""Run external tools (yt-dlp, FFmpeg) safely.

Arguments are always a list (never a shell, spec 7), there is no console window, and on
Windows each process is placed in a Job Object with KILL_ON_JOB_CLOSE: stopping it stops
the FFmpeg children yt-dlp starts, and if OpenDM dies the OS cleans them all up.
"""

import asyncio
import contextlib
import ctypes
import sys
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from ctypes import wintypes
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
# yt-dlp -J prints a page's info as one line, often several MB for YouTube; asyncio's
# default line limit is 64 KiB.
LINE_LIMIT = 256 * 1024 * 1024
_KILL_ON_JOB_CLOSE = 0x2000
_EXTENDED_LIMIT_INFO = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]  # fmt: skip


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobObject:
    """A Windows Job Object that kills its processes when terminated or closed."""

    def __init__(self) -> None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = k32
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
            self.handle, _EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def assign(self, pid: int) -> None:
        process = self._k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            raise OSError(ctypes.get_last_error(), "OpenProcess failed")
        try:
            if not self._k32.AssignProcessToJobObject(self.handle, process):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            self._k32.CloseHandle(process)

    def terminate(self) -> None:
        if self.handle:
            self._k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._k32.CloseHandle(self.handle)
            self.handle = None


class ToolProcess:
    """A running tool with line-by-line stdout and the last lines of stderr."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        job: _JobObject | None,
        on_stderr: Callable[[str], None] | None = None,
    ) -> None:
        self.proc = proc
        self._job = job
        self._on_stderr = on_stderr
        self.stderr_tail: deque[str] = deque(maxlen=200)
        self._stderr_task = asyncio.create_task(self._collect_stderr())

    @classmethod
    async def start(
        cls,
        args: Sequence[str],
        cwd: Path | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ) -> "ToolProcess":
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            creationflags=flags,
            limit=LINE_LIMIT,
        )
        job = None
        if sys.platform == "win32":
            job = _JobObject()
            try:
                job.assign(proc.pid)
            except OSError:
                job.close()
                job = None
        return cls(proc, job, on_stderr)

    async def _collect_stderr(self) -> None:
        assert self.proc.stderr is not None
        async for raw in self.proc.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            self.stderr_tail.append(line)
            if self._on_stderr is not None:
                self._on_stderr(line)

    async def lines(self) -> AsyncIterator[str]:
        assert self.proc.stdout is not None
        async for raw in self.proc.stdout:
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")

    async def wait(self) -> int:
        code = await self.proc.wait()
        with contextlib.suppress(asyncio.CancelledError):
            await self._stderr_task
        return code

    @property
    def stderr(self) -> str:
        return "\n".join(self.stderr_tail)

    def kill(self) -> None:
        """Stop the tool and everything it started."""
        if self._job is not None:
            self._job.terminate()
        elif self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.kill()

    async def stop(self) -> None:
        self.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.wait(), 10)
        self.close()

    def close(self) -> None:
        if self._job is not None:
            self._job.close()
            self._job = None


async def run_tool(args: Sequence[str], timeout: float = 120) -> tuple[int, str, str]:
    """Run to completion; returns (exit code, stdout, stderr)."""
    process = await ToolProcess.start(args)
    out: list[str] = []
    try:
        async with asyncio.timeout(timeout):
            async for line in process.lines():
                out.append(line)
            code = await process.wait()
    except BaseException:
        await process.stop()
        raise
    process.close()
    return code, "\n".join(out), process.stderr
