"""IPC server (Qt, GUI thread) and the Qt-free client."""

import concurrent.futures
import json
import sys
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from opendm.ipc import client
from opendm.ipc.protocol import Request
from opendm.ipc.server import IpcServer


def in_thread(qtbot, fn: Callable[[], Any]) -> Any:
    """Run a blocking client call while the Qt event loop keeps serving."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=10_000)
    if "error" in box:
        raise box["error"]
    return box["value"]


@pytest.fixture
def served(qtbot):
    calls: list[Request] = []
    executor = concurrent.futures.ThreadPoolExecutor(1)

    def handler(req: Request) -> Any:
        calls.append(req)
        if req.cmd == "ping":
            return "pong"
        if req.cmd == "list":
            return executor.submit(lambda: [{"id": "j1"}])  # completes on another thread
        if req.cmd == "pause":
            raise KeyError("no such job")
        return {"echo": req.args}

    name = f"opendm-test-{uuid.uuid4().hex[:8]}"
    server = IpcServer(handler)
    assert server.listen(name)
    yield name, calls
    server.close()
    executor.shutdown()


def test_request_reply(qtbot, served) -> None:
    name, calls = served
    assert in_thread(qtbot, lambda: client.request("ping", name=name)) == "pong"
    assert in_thread(qtbot, lambda: client.request("list", name=name)) == [{"id": "j1"}]
    args = {"url": "https://example.com/a.zip", "start": False}
    assert in_thread(qtbot, lambda: client.request("add", args, name=name)) == {"echo": args}
    assert [c.cmd for c in calls] == ["ping", "list", "add"]


def test_handler_errors_become_error_replies(qtbot, served) -> None:
    name, _ = served
    with pytest.raises(client.IpcError, match="no such job"):
        in_thread(qtbot, lambda: client.request("pause", {"job_id": "x"}, name=name))


def test_invalid_messages_are_rejected(qtbot, served) -> None:
    name, calls = served
    reply = in_thread(qtbot, lambda: client.exchange(b'{"v":1,"cmd":"rm -rf"}\n', name=name))
    assert json.loads(reply) == {"v": 1, "ok": False, "error": "unknown command: 'rm -rf'"}
    reply = in_thread(qtbot, lambda: client.exchange(b"garbage\n", name=name))
    assert json.loads(reply)["ok"] is False
    assert calls == []  # the handler never saw them


def test_not_running(qtbot) -> None:
    with pytest.raises(client.AppNotRunning):
        client.request("ping", name=f"opendm-absent-{uuid.uuid4().hex[:8]}")


def test_pipe_alone_is_not_a_single_instance_lock(qtbot, served) -> None:
    # Windows allows several pipe instances with one name, which is why
    # ipc.single_instance uses a named mutex instead.
    name, _ = served
    other = IpcServer(lambda req: None)
    other.listen(name)
    other.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pipe permissions")
def test_pipe_is_open_only_to_this_user(qtbot, served) -> None:
    import ctypes
    from ctypes import wintypes

    name, _ = served
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]  # fmt: skip
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    # Open the pipe only to read its permissions (READ_CONTROL, OPEN_EXISTING).
    handle = k32.CreateFileW(rf"\\.\pipe\{name}", 0x20000, 0, None, 3, 0, None)
    assert handle and handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    sd, dacl = ctypes.c_void_p(), ctypes.c_void_p()
    adv.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]  # fmt: skip
    try:
        err = adv.GetSecurityInfo(
            handle, 6, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd)
        )  # SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION
    finally:
        k32.CloseHandle(handle)
        qtbot.wait(200)  # let the server see the connect and the disconnect
    assert err == 0, err
    text = wintypes.LPWSTR()
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p,
    ]  # fmt: skip
    assert adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        sd, 1, 4, ctypes.byref(text), None
    )
    sddl = text.value or ""
    for broad in ("WD", "AU", "BU", "AN"):  # Everyone, Authenticated Users, Users, Anonymous
        assert f";;;{broad})" not in sddl, sddl
    assert "S-1-5-21-" in sddl  # this user's SID is granted access
