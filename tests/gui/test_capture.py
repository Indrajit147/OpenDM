"""Downloads and link lists handed over by the browser extension (M6)."""

from PySide6.QtCore import Qt

from opendm.core.models import DownloadRequest, JobState
from opendm.gui.dialogs.start_download import StartDownloadDialog
from opendm.ipc.protocol import Request, decode_request, encode_request
from tests.gui.conftest import GuiApp
from tests.server.app import COOKIE_NAME, COOKIE_VALUE, FaultServer, content_sha256

WAIT = 20_000


def ipc(gui: GuiApp, cmd: str, args: dict) -> object:
    """Through the same validation as the pipe, then the app's handler."""
    request: Request = decode_request(encode_request(cmd, args))
    return gui.handle_ipc(request)


def record_start_dialogs(gui: GuiApp, monkeypatch) -> list[StartDownloadDialog]:
    """The dialogs this test opens (other tests may leave theirs open on the shared app)."""
    opened: list[StartDownloadDialog] = []
    original = gui.window.open_start_dialog

    def wrapper(*args, **kwargs) -> StartDownloadDialog:
        opened.append(original(*args, **kwargs))
        return opened[-1]

    monkeypatch.setattr(gui.window, "open_start_dialog", wrapper)
    return opened


def test_capture_with_cookies_downloads_the_protected_file(
    qtbot, gui: GuiApp, server: FaultServer, monkeypatch
) -> None:
    opened = record_start_dialogs(gui, monkeypatch)
    url = server.url("/protected/members.zip?size=50000")
    reply = ipc(gui, "capture", {
        "url": url, "cookies": f"{COOKIE_NAME}={COOKIE_VALUE}",
        "referrer": server.url("/page"), "user_agent": "Mozilla/5.0 test",
    })  # fmt: skip
    assert reply == {"shown": "start"}
    assert len(opened) == 1
    dialog = opened[0]
    assert dialog.isVisible()
    qtbot.waitUntil(lambda: dialog.probe_result is not None, timeout=WAIT)  # probe sent the cookie
    assert dialog.name_edit.text() == "members.zip"
    dialog.start_button.click()

    def completed() -> bool:
        jobs = gui.window.model.jobs()
        return bool(jobs) and jobs[0].state is JobState.COMPLETED

    qtbot.waitUntil(completed, timeout=WAIT)
    job = gui.window.model.jobs()[0]
    assert job.sha256 == content_sha256(50000, 1)
    assert job.request.referrer == server.url("/page")
    assert job.request.user_agent == "Mozilla/5.0 test"


def test_capture_without_the_cookie_fails_visibly(
    qtbot, gui: GuiApp, server: FaultServer, monkeypatch
) -> None:
    opened = record_start_dialogs(gui, monkeypatch)
    ipc(gui, "capture", {"url": server.url("/protected/members.zip?size=50000")})
    dialog = opened[0]
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=WAIT)
    assert "403" in dialog.error_label.text()


def test_capture_media_opens_the_video_flow(gui: GuiApp, monkeypatch) -> None:
    seen: list[DownloadRequest] = []
    monkeypatch.setattr(gui, "open_media", seen.append)
    reply = ipc(gui, "capture", {"url": "https://example.com/watch?v=1", "media": True,
                                 "cookies": "a=1", "page_url": "https://example.com/"})  # fmt: skip
    assert reply == {"shown": "media"}
    assert seen[0].url == "https://example.com/watch?v=1"
    assert seen[0].cookies == "a=1" and seen[0].referrer == "https://example.com/"


def test_capture_links_lets_the_user_pick(qtbot, gui: GuiApp, server: FaultServer) -> None:
    urls = [
        server.url("/file/setup.exe?size=100"),
        server.url("/file/manual.pdf?size=100"),
        server.url("/about"),  # an ordinary page: not pre-selected
        server.url("/file/manual.pdf?size=100"),  # duplicate
    ]
    reply = ipc(gui, "capture_links", {"urls": urls, "page_url": server.url("/downloads"),
                                       "page_title": "Downloads"})  # fmt: skip
    assert reply == {"shown": "links", "count": 3}
    dialog = gui.link_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.selected() == urls[:2]
    dialog.kind.setCurrentIndex(dialog.kind.findText("Documents"))
    shown = [dialog.list.item(i) for i in range(dialog.list.count())
             if not dialog.list.item(i).isHidden()]  # fmt: skip
    assert [i.data(Qt.ItemDataRole.UserRole) for i in shown] == [urls[1]]
    dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)  # drop setup.exe
    dialog.accept()

    def done() -> bool:
        jobs = gui.window.model.jobs()
        return len(jobs) == 1 and jobs[0].state is JobState.COMPLETED

    qtbot.waitUntil(done, timeout=WAIT)
    job = gui.window.model.jobs()[0]
    assert job.name == "manual.pdf" and job.request.referrer == server.url("/downloads")
