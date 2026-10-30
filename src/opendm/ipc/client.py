"""IPC client without Qt (used by opendm-cli, the Native Messaging host and second launches).

On Windows it opens the server's named pipe ``\\\\.\\pipe\\<name>`` as a file.
"""

import errno
import getpass
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from opendm.ipc.protocol import MAX_MESSAGE, encode_request, pipe_name

_PIPE_BUSY = 231  # ERROR_PIPE_BUSY


class AppNotRunning(Exception):
    """No OpenDM app is listening for this user."""


class IpcError(Exception):
    """The app answered with an error, or the exchange failed."""


def default_name() -> str:
    """The per-user pipe; ``OPENDM_IPC_NAME`` overrides it (tests use a private one)."""
    return os.environ.get("OPENDM_IPC_NAME") or pipe_name(getpass.getuser())


def _exchange_windows(name: str, data: bytes) -> bytes:
    path = rf"\\.\pipe\{name}"
    for _ in range(100):
        try:
            pipe = open(path, "r+b", buffering=0)  # noqa: SIM115
            break
        except FileNotFoundError as exc:
            raise AppNotRunning(name) from exc
        except OSError as exc:
            if getattr(exc, "winerror", None) == _PIPE_BUSY:
                time.sleep(0.05)
                continue
            raise AppNotRunning(name) from exc
    else:
        raise IpcError("the app is busy")
    with pipe:
        pipe.write(data)
        reply = bytearray()
        while b"\n" not in reply:
            chunk = pipe.read(65536)
            if not chunk:
                break
            reply += chunk
            if len(reply) > MAX_MESSAGE:
                raise IpcError("reply too large")
    return bytes(reply)


def _exchange_unix(name: str, data: bytes) -> bytes:
    path = Path(tempfile.gettempdir()) / name
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:  # type: ignore[attr-defined]
        try:
            sock.connect(str(path))
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ECONNREFUSED):
                raise AppNotRunning(name) from exc
            raise
        sock.sendall(data)
        reply = bytearray()
        while b"\n" not in reply:
            chunk = sock.recv(65536)
            if not chunk:
                break
            reply += chunk
    return bytes(reply)


def exchange(data: bytes, *, name: str | None = None, timeout: float = 15.0) -> bytes:
    """Send raw bytes, return the raw reply line. Raises AppNotRunning or IpcError."""
    name = name or default_name()
    impl = _exchange_windows if sys.platform == "win32" else _exchange_unix
    outcome: dict[str, Any] = {}

    def worker() -> None:
        try:
            outcome["reply"] = impl(name, data)
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise IpcError("timed out waiting for the app")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["reply"]


def request(
    cmd: str, args: dict[str, Any] | None = None, *, name: str | None = None, timeout: float = 15.0
) -> Any:
    """Send one command and return its result."""
    reply = exchange(encode_request(cmd, args), name=name, timeout=timeout)
    try:
        message = json.loads(reply.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise IpcError("the app sent an invalid reply") from exc
    if not isinstance(message, dict) or not message.get("ok"):
        error = message.get("error") if isinstance(message, dict) else None
        raise IpcError(error or "request failed")
    return message.get("result")
