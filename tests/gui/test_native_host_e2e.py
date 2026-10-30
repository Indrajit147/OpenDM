"""The real host process: framed stdin -> named pipe -> app, reply on stdout."""

import json
import os
import struct
import subprocess
import sys
import uuid
from typing import Any

from opendm.ipc.protocol import Request
from opendm.ipc.server import IpcServer
from tests.gui.test_ipc import in_thread


def frame(obj: object) -> bytes:
    data = json.dumps(obj).encode()
    return struct.pack("<I", len(data)) + data


def run_host(qtbot, message: object, env: dict[str, str] | None = None) -> dict[str, Any]:
    def run() -> bytes:
        done = subprocess.run(
            [sys.executable, "-m", "opendm.host", "chrome-extension://test/"],
            input=frame(message), capture_output=True, timeout=60,
            env={**os.environ, **(env or {})},
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        return done.stdout

    out = in_thread(qtbot, run)
    (length,) = struct.unpack("<I", out[:4])
    assert len(out) == 4 + length
    return json.loads(out[4:])


def test_host_forwards_a_download(qtbot) -> None:
    received: list[Request] = []

    def handler(req: Request) -> Any:
        received.append(req)
        return {"shown": "start-dialog"}

    server = IpcServer(handler)
    assert server.listen(os.environ["OPENDM_IPC_NAME"])
    try:
        reply = run_host(qtbot, {
            "type": "download", "url": "https://example.com/a.zip", "cookies": "s=1",
            "referrer": "https://example.com/", "fileSize": 2048,
        })  # fmt: skip
    finally:
        server.close()
    assert reply == {"ok": True, "result": {"shown": "start-dialog"}}
    assert [(r.cmd, r.args) for r in received] == [("capture", {
        "url": "https://example.com/a.zip", "cookies": "s=1",
        "referrer": "https://example.com/", "file_size": 2048,
    })]  # fmt: skip


def test_host_rejects_bad_messages_without_contacting_the_app(qtbot) -> None:
    reply = run_host(qtbot, {"type": "download", "url": "file:///C:/Windows/win.ini"})
    assert reply["ok"] is False and reply["error"] == "invalid"


def test_host_when_the_app_cannot_be_started(qtbot) -> None:
    env = {
        "OPENDM_IPC_NAME": f"opendm-absent-{uuid.uuid4().hex[:8]}",
        "OPENDM_HOST_LAUNCH": f"{sys.executable}|-c|pass",  # "starts" but never listens
        "OPENDM_HOST_WAIT": "1",
    }
    reply = run_host(qtbot, {"type": "download", "url": "https://example.com/a.zip"}, env)
    assert reply == {"ok": False, "error": "unavailable",
                     "message": "OpenDM is not running and could not be started"}  # fmt: skip
