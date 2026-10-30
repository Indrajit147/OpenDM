"""Hand a browser message to the running app, starting the app if needed."""

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from opendm.core.branding import GUI_EXE
from opendm.host.protocol import BrowserMessageError, translate
from opendm.ipc import client as ipc_client

DEFAULT_WAIT = float(os.environ.get("OPENDM_HOST_WAIT", "15"))  # for a freshly started app
_DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED, NEW_PROCESS_GROUP, NO_WINDOW


def app_command() -> list[str]:
    """How to start OpenDM minimized: the packaged exe next to us, or the dev venv."""
    override = os.environ.get("OPENDM_HOST_LAUNCH")  # tests: a harmless command
    if override:
        return override.split("|")
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name(GUI_EXE)), "--minimized"]
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else python), "-m", "opendm", "--minimized"]


def launch_app() -> bool:
    """Start the app without inheriting the browser's pipes; True if it was started."""
    try:
        subprocess.Popen(
            app_command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=_DETACHED if sys.platform == "win32" else 0,
        )
    except OSError:
        return False
    return True


def handle(
    message: dict[str, Any],
    *,
    request: Callable[..., Any] = ipc_client.request,
    launch: Callable[[], bool] = launch_app,
    wait: float | None = None,
) -> dict[str, Any]:
    wait = DEFAULT_WAIT if wait is None else wait
    """Process one browser message; always returns a reply for the extension."""
    try:
        cmd, args = translate(message)
    except BrowserMessageError as exc:
        return {"ok": False, "error": "invalid", "message": str(exc)}
    try:
        return {"ok": True, "result": request(cmd, args)}
    except ipc_client.AppNotRunning:
        pass
    except ipc_client.IpcError as exc:
        return {"ok": False, "error": "rejected", "message": str(exc)}

    unavailable = {
        "ok": False,
        "error": "unavailable",
        "message": "OpenDM is not running and could not be started",
    }
    if cmd == "ping" or not launch():  # a status check never starts the app
        return unavailable
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            return {"ok": True, "result": request(cmd, args)}
        except ipc_client.AppNotRunning:
            continue
        except ipc_client.IpcError as exc:
            return {"ok": False, "error": "rejected", "message": str(exc)}
    return unavailable
