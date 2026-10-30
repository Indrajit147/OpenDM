"""Native Messaging host: framing, message translation and app hand-off (no browser, no Qt)."""

import io
import json
import struct

import pytest

from opendm.host.protocol import (
    MAX_FROM_BROWSER,
    MAX_TO_BROWSER,
    BrowserMessageError,
    read_message,
    translate,
    write_message,
)
from opendm.host.relay import handle
from opendm.ipc.client import AppNotRunning, IpcError


def frame(obj: object) -> bytes:
    data = json.dumps(obj).encode()
    return struct.pack("<I", len(data)) + data


# --- framing ---------------------------------------------------------------------------------


def test_read_and_write_round_trip() -> None:
    assert read_message(io.BytesIO(frame({"type": "ping"}))) == {"type": "ping"}
    out = io.BytesIO()
    write_message(out, {"ok": True, "result": "pong"})
    raw = out.getvalue()
    assert struct.unpack("<I", raw[:4])[0] == len(raw) - 4
    assert json.loads(raw[4:]) == {"ok": True, "result": "pong"}


def test_end_of_input_is_none() -> None:
    assert read_message(io.BytesIO(b"")) is None


@pytest.mark.parametrize(
    "data",
    [
        b"\x05\x00",  # truncated length
        struct.pack("<I", 10) + b"{}",  # truncated body
        struct.pack("<I", MAX_FROM_BROWSER + 1),  # too large
        struct.pack("<I", 3) + b"[1]",  # not an object
        struct.pack("<I", 3) + b"{x}",  # not JSON
        struct.pack("<I", 2) + b"\xff\xfe",  # not UTF-8
    ],
)
def test_bad_frames(data: bytes) -> None:
    with pytest.raises(BrowserMessageError):
        read_message(io.BytesIO(data))


def test_reply_size_limit() -> None:
    with pytest.raises(BrowserMessageError):
        write_message(io.BytesIO(), {"ok": True, "result": "x" * MAX_TO_BROWSER})


# --- translation -----------------------------------------------------------------------------


def test_translate_download() -> None:
    cmd, args = translate({
        "type": "download", "url": "https://example.com/a.zip", "pageUrl": "https://example.com/",
        "pageTitle": "Example", "referrer": "https://example.com/", "userAgent": "UA/1",
        "cookies": "s=1", "filename": "a.zip", "fileSize": 1234, "media": False,
    })  # fmt: skip
    assert cmd == "capture"
    assert args == {
        "url": "https://example.com/a.zip", "page_url": "https://example.com/",
        "page_title": "Example", "referrer": "https://example.com/", "user_agent": "UA/1",
        "cookies": "s=1", "filename": "a.zip", "file_size": 1234, "media": False,
    }  # fmt: skip


def test_translate_links_and_status() -> None:
    cmd, args = translate({"type": "links", "urls": ["https://h/a", "https://h/b"],
                           "pageUrl": "https://h/"})  # fmt: skip
    assert cmd == "capture_links" and args["urls"] == ["https://h/a", "https://h/b"]
    assert translate({"type": "status"}) == ("ping", {})


@pytest.mark.parametrize(
    "message",
    [
        {"type": "format_disk"},
        {"type": "download"},  # no url
        {"type": "download", "url": "file:///C:/Windows/win.ini"},
        {"type": "download", "url": "javascript:alert(1)"},
        {"type": "download", "url": "https://h/a", "evil": 1},
        {"type": "download", "url": "https://h/a", "cookies": "x" * 70_000},
        {"type": "download", "url": "https://h/a", "media": "yes"},
        {"type": "links", "urls": ["https://h/a", "ftp://h/b"]},
        {"type": "links", "urls": "https://h/a"},
        {"url": "https://h/a"},
    ],
)
def test_translate_rejects(message: dict) -> None:
    with pytest.raises(BrowserMessageError):
        translate(message)


# --- hand-off to the app -----------------------------------------------------------------------


class FakeApp:
    def __init__(self, running: bool = True, starts: bool = True, error: str | None = None):
        self.running = running
        self.starts = starts
        self.error = error
        self.requests: list[tuple[str, dict]] = []
        self.launches = 0

    def request(self, cmd: str, args: dict | None = None, **_: object) -> object:
        if not self.running:
            raise AppNotRunning("x")
        if self.error:
            raise IpcError(self.error)
        self.requests.append((cmd, args or {}))
        return "pong" if cmd == "ping" else {"shown": True}

    def launch(self) -> bool:
        self.launches += 1
        if self.starts:
            self.running = True
        return True


def test_handle_forwards_to_running_app() -> None:
    app = FakeApp()
    reply = handle({"type": "download", "url": "https://h/a.zip"}, request=app.request,
                   launch=app.launch, wait=0.5)  # fmt: skip
    assert reply == {"ok": True, "result": {"shown": True}}
    assert app.requests == [("capture", {"url": "https://h/a.zip"})]
    assert app.launches == 0


def test_handle_starts_the_app_when_needed() -> None:
    app = FakeApp(running=False)
    reply = handle({"type": "download", "url": "https://h/a.zip"}, request=app.request,
                   launch=app.launch, wait=2)  # fmt: skip
    assert reply["ok"] and app.launches == 1


def test_handle_reports_unavailable_when_the_app_will_not_start() -> None:
    app = FakeApp(running=False, starts=False)
    reply = handle({"type": "download", "url": "https://h/a.zip"}, request=app.request,
                   launch=app.launch, wait=0.3)  # fmt: skip
    assert reply == {"ok": False, "error": "unavailable",
                     "message": "OpenDM is not running and could not be started"}  # fmt: skip


def test_status_never_starts_the_app() -> None:
    app = FakeApp(running=False)
    reply = handle({"type": "status"}, request=app.request, launch=app.launch, wait=0.3)
    assert reply["ok"] is False and reply["error"] == "unavailable"
    assert app.launches == 0


def test_handle_invalid_and_rejected() -> None:
    app = FakeApp()
    bad = handle({"type": "download", "url": "file:///x"}, request=app.request, launch=app.launch)
    assert bad["ok"] is False and bad["error"] == "invalid"
    assert app.requests == []
    refused = FakeApp(error="busy")
    reply = handle({"type": "status"}, request=refused.request, launch=refused.launch)
    assert reply == {"ok": False, "error": "rejected", "message": "busy"}
