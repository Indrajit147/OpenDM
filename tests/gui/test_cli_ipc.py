"""opendm-cli talking to a running app over the named pipe (fake app handler)."""

import os
from pathlib import Path
from typing import Any

import pytest

from opendm.cli.__main__ import main
from opendm.ipc.protocol import Request
from opendm.ipc.server import IpcServer
from tests.gui.test_ipc import in_thread


@pytest.fixture
def app(qtbot):
    requests: list[Request] = []

    def handler(req: Request) -> Any:
        requests.append(req)
        if req.cmd == "add":
            return {"id": "job123", "name": "a.zip"}
        if req.cmd == "list":
            return [
                {"id": "job123", "name": "a.zip", "state": "downloading", "downloaded": 50,
                 "size": 200},
                {"id": "job456", "name": "b.bin", "state": "queued", "downloaded": 0,
                 "size": None},
            ]  # fmt: skip
        if req.cmd == "resume" and req.args["job_id"] == "missing":
            raise KeyError("missing")
        return None

    server = IpcServer(handler)
    assert server.listen(os.environ["OPENDM_IPC_NAME"])
    yield requests
    server.close()


def test_get_adds_to_the_app(qtbot, app, tmp_path: Path, capsys) -> None:
    argv = ["get", "https://example.com/a.zip", "-o", str(tmp_path), "-c", "4",
            "--limit", "1M", "--cookie", "s=1", "--header", "X-A: 1"]  # fmt: skip
    assert in_thread(qtbot, lambda: main(argv)) == 0
    assert "Added job123: a.zip" in capsys.readouterr().out
    (req,) = app
    assert req.cmd == "add"
    assert req.args == {
        "url": "https://example.com/a.zip", "connections": 4, "dest_dir": str(tmp_path),
        "speed_limit": 1024 * 1024, "cookies": "s=1", "headers": {"X-A": "1"},
    }  # fmt: skip


def test_list(qtbot, app, capsys) -> None:
    assert in_thread(qtbot, lambda: main(["list"])) == 0
    out = capsys.readouterr().out
    assert "job123  downloading  25.0%" in out
    assert "job456  queued" in out and "b.bin" in out


def test_pause_resume_remove(qtbot, app, capsys) -> None:
    assert in_thread(qtbot, lambda: main(["pause", "job123"])) == 0
    assert in_thread(qtbot, lambda: main(["remove", "job123", "--delete-file"])) == 0
    assert [(r.cmd, r.args) for r in app] == [
        ("pause", {"job_id": "job123"}),
        ("remove", {"job_id": "job123", "delete_file": True}),
    ]
    assert in_thread(qtbot, lambda: main(["resume", "missing"])) == 1
    assert "missing" in capsys.readouterr().err
