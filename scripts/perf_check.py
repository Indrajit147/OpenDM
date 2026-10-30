r"""Memory and responsiveness of the built app with 10 downloads running (spec 7, M9).

    .venv\Scripts\python.exe scripts\perf_check.py

Uses the programs unpacked by scripts\smoke_dist.py (build\smoke\OpenDM), a private pipe, its
own data folder and the local test server, so your installed OpenDM is not touched. Starts
OpenDM.exe in the tray, adds 10 rate-limited downloads, and while they run samples
  - memory of OpenDM.exe (working set and private bytes; spec: under ~250 MB),
  - how long the window thread takes to answer a ping (it must never freeze).
Then quits the app and deletes the downloaded data (about 600 MB at most).
"""

import ctypes
import os
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from opendm.core.paths import database_path  # noqa: E402
from opendm.ipc import client as ipc_client  # noqa: E402
from opendm.storage.db import Database  # noqa: E402
from opendm.storage.repositories import SettingsRepository  # noqa: E402
from tests.server.app import FaultServer  # noqa: E402

APP = ROOT / "build" / "smoke" / "OpenDM"
WORK = ROOT / "build" / "perf"
DOWNLOADS = 10
MEMORY_LIMIT_MB = 250
PING_LIMIT_MS = 250


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]  # fmt: skip


def memory_mb(pid: int) -> tuple[float, float]:
    """(working set, private bytes) in MB."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    handle = k32.OpenProcess(0x1000 | 0x0010, False, pid)  # limited query + VM read
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    try:
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
    finally:
        k32.CloseHandle(handle)
    return counters.WorkingSetSize / 2**20, counters.PrivateUsage / 2**20


def main() -> int:
    gui = APP / "OpenDM.exe"
    if not gui.is_file():
        print("run scripts\\smoke_dist.py first (it unpacks build\\smoke\\OpenDM)")
        return 2
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(APP / "data", ignore_errors=True)
    pipe = f"opendm-perf-{uuid.uuid4().hex[:8]}"
    env = {**os.environ, "OPENDM_IPC_NAME": pipe}
    db = Database(database_path(APP / "data"))
    settings = SettingsRepository(db)
    settings.set("first_run_done", True)
    settings.set("per_host", 32)  # all downloads hit 127.0.0.1: let all 10 run at once
    settings.set("connections", 3)
    settings.set("download_dir", str(WORK))
    db.close()

    with FaultServer() as server:
        proc = subprocess.Popen([gui, "--minimized"], env=env)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    ipc_client.request("ping", {}, name=pipe, timeout=2)
                    break
                except (ipc_client.AppNotRunning, ipc_client.IpcError):
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.5)
            idle_ws, idle_private = memory_mb(proc.pid)
            for i in range(DOWNLOADS):
                url = server.url(f"/file/perf{i}.bin?size=60M&rate=256K")
                ipc_client.request("add", {"url": url, "dest_dir": str(WORK)}, name=pipe)
            deadline = time.monotonic() + 30
            while True:
                jobs = ipc_client.request("list", {}, name=pipe)
                running = sum(1 for j in jobs if j["state"] == "downloading")
                if running == DOWNLOADS:
                    break
                if time.monotonic() > deadline:
                    print(f"only {running} of {DOWNLOADS} downloads running")
                    return 1
                time.sleep(0.5)
            samples, pings = [], []
            for _ in range(20):
                samples.append(memory_mb(proc.pid))
                started = time.perf_counter()
                ipc_client.request("ping", {}, name=pipe)
                pings.append((time.perf_counter() - started) * 1000)
                time.sleep(1)
            jobs = ipc_client.request("list", {}, name=pipe)
            still = sum(1 for j in jobs if j["state"] == "downloading")
            ipc_client.request("quit", {}, name=pipe, timeout=5)
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(APP / "data", ignore_errors=True)

    peak_ws = max(s[0] for s in samples)
    peak_private = max(s[1] for s in samples)
    print(f"idle:  working set {idle_ws:.0f} MB, private {idle_private:.0f} MB")
    print(f"{DOWNLOADS} downloads: working set peak {peak_ws:.0f} MB, "
          f"private peak {peak_private:.0f} MB (limit {MEMORY_LIMIT_MB} MB)")  # fmt: skip
    print(f"window thread ping: median {statistics.median(pings):.0f} ms, "
          f"max {max(pings):.0f} ms (limit {PING_LIMIT_MS} ms)")  # fmt: skip
    print(f"downloads still running at the end: {still} of {DOWNLOADS}")
    ok = peak_ws < MEMORY_LIMIT_MB and max(pings) < PING_LIMIT_MS and still == DOWNLOADS
    print("perf check passed" if ok else "perf check FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
