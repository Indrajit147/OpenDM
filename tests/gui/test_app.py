"""GUI smoke tests (pytest-qt, offscreen) against the local test server."""

import dataclasses
import os
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from opendm.core.events import PowerRequested
from opendm.core.models import AfterAction, Job, JobState
from opendm.gui.dialogs.wizard import FirstRunWizard
from opendm.gui.main_window import MainWindow
from opendm.ipc import client
from opendm.ipc.single_instance import InstanceLock
from tests.gui.conftest import GuiApp
from tests.gui.test_ipc import in_thread
from tests.server.app import FaultServer, content_sha256

WAIT = 20_000


def job_named(window: MainWindow, name: str) -> Job | None:
    return next((j for j in window.model.jobs() if j.name == name), None)


def wait_state(qtbot, window: MainWindow, name: str, state: JobState) -> Job:
    qtbot.waitUntil(lambda: (j := job_named(window, name)) is not None and j.state is state,
                    timeout=WAIT)  # fmt: skip
    job = job_named(window, name)
    assert job is not None
    return job


def select(window: MainWindow, name: str) -> None:
    window.select_view("all")
    for row in range(window.proxy.rowCount()):
        index = window.proxy.index(row, 0)
        if window.proxy.data(index) == name:
            window.table.selectRow(row)
            return
    raise AssertionError(f"{name} not in table")


def test_window_opens(gui: GuiApp) -> None:
    window = gui.window
    assert window.isVisible()
    assert window.windowTitle() == "OpenDM"
    assert [c.name for c in window.categories][:2] == ["Video", "Audio"]
    assert window.sidebar.topLevelItemCount() == 5
    assert gui.ipc_listening


def test_add_url_start_dialog_and_completion(
    qtbot, gui: GuiApp, server: FaultServer, tmp_path
) -> None:
    dialog = gui.window.add_urls([server.url("/file/pack.zip?size=1M")])
    assert dialog is not None
    qtbot.waitUntil(lambda: dialog.probe_result is not None, timeout=WAIT)
    assert dialog.name_edit.text() == "pack.zip"
    assert dialog.size_label.text() == "1.0 MiB"
    assert dialog.category_box.currentText() == "Compressed"
    assert Path(dialog.folder_edit.text()) == tmp_path / "dl" / "Compressed"
    dialog.start_button.click()
    job = wait_state(qtbot, gui.window, "pack.zip", JobState.COMPLETED)
    assert job.final_path == tmp_path / "dl" / "Compressed" / "pack.zip"
    assert job.sha256 == content_sha256(1024 * 1024, 1)
    gui.window.select_view("finished")
    assert gui.window.proxy.rowCount() == 1
    gui.window.select_view("unfinished")
    assert gui.window.proxy.rowCount() == 0


def test_probe_failure_is_shown(qtbot, gui: GuiApp, server: FaultServer) -> None:
    dialog = gui.window.add_urls([server.url("/status/404")])
    assert dialog is not None
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=WAIT)
    assert "404" in dialog.error_label.text()


def test_batch_add(qtbot, gui: GuiApp, server: FaultServer, tmp_path) -> None:
    gui.window.add_urls(
        [server.url("/file/clip.mp4?size=1000"), server.url("/file/doc.pdf?size=1000")]
    )
    wait_state(qtbot, gui.window, "clip.mp4", JobState.COMPLETED)
    wait_state(qtbot, gui.window, "doc.pdf", JobState.COMPLETED)
    assert (tmp_path / "dl" / "Video" / "clip.mp4").exists()
    assert (tmp_path / "dl" / "Documents" / "doc.pdf").exists()


def test_pause_resume_from_toolbar(qtbot, gui: GuiApp, server: FaultServer) -> None:
    gui.window.add_urls([server.url("/file/slow.bin?size=2M&rate=256K")], ask=False)
    wait_state(qtbot, gui.window, "slow.bin", JobState.DOWNLOADING)
    select(gui.window, "slow.bin")
    assert gui.window.pause_action.isEnabled()
    gui.window.pause_action.trigger()
    wait_state(qtbot, gui.window, "slow.bin", JobState.PAUSED)
    select(gui.window, "slow.bin")
    gui.window.resume_action.trigger()
    wait_state(qtbot, gui.window, "slow.bin", JobState.DOWNLOADING)
    gui.window.stop_all_action.trigger()
    wait_state(qtbot, gui.window, "slow.bin", JobState.PAUSED)


def test_details_window_shows_segments_and_speed(qtbot, gui: GuiApp, server: FaultServer) -> None:
    gui.window.add_urls([server.url("/file/seg.bin?size=2M&rate=256K")], ask=False)
    job = wait_state(qtbot, gui.window, "seg.bin", JobState.DOWNLOADING)
    details = gui.window.show_details(job)
    qtbot.waitUntil(lambda: details.segment_map.filled_fraction() > 0.05, timeout=WAIT)
    qtbot.waitUntil(lambda: len(details.graph.samples) >= 1, timeout=WAIT)
    assert int(details.connections_label.text()) >= 1
    assert details.toggle_button.text() == "Pause"
    details.toggle_button.click()
    wait_state(qtbot, gui.window, "seg.bin", JobState.PAUSED)
    qtbot.waitUntil(lambda: details.toggle_button.text() == "Resume", timeout=WAIT)
    details.close()


def test_delete_with_file(qtbot, gui: GuiApp, server: FaultServer, tmp_path) -> None:
    gui.window.add_urls([server.url("/file/gone.bin?size=1000")], ask=False)
    job = wait_state(qtbot, gui.window, "gone.bin", JobState.COMPLETED)
    assert job.final_path is not None and job.final_path.exists()
    select(gui.window, "gone.bin")
    gui.window.delete_selected(confirm=lambda n: (True, True))
    qtbot.waitUntil(lambda: job_named(gui.window, "gone.bin") is None, timeout=WAIT)
    assert not job.final_path.exists()


def test_delete_can_be_declined(qtbot, gui: GuiApp, server: FaultServer) -> None:
    gui.window.add_urls([server.url("/file/keep.bin?size=1000")], ask=False)
    wait_state(qtbot, gui.window, "keep.bin", JobState.COMPLETED)
    select(gui.window, "keep.bin")
    gui.window.delete_selected(confirm=lambda n: (False, True))
    qtbot.wait(300)
    assert job_named(gui.window, "keep.bin") is not None


def test_programs_need_confirmation_to_open(qtbot, gui: GuiApp, tmp_path) -> None:
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    job = Job(request=None, final_path=exe, state=JobState.COMPLETED)  # type: ignore[arg-type]
    asked: list[Path] = []
    assert gui.window.open_file(job, confirm=lambda p: asked.append(p) or False) is False
    assert asked == [exe]


def test_settings_dialog_saves(qtbot, gui: GuiApp) -> None:
    dialog = gui.open_settings()
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog.connections.setValue(12)
    dialog.limit.setValue(512)
    dialog.category_table.item(0, 2).setText("Movies")
    dialog.accept()
    assert gui.settings.theme == "dark"
    assert gui.settings.connections == 12 and gui.settings.global_limit == 512 * 1024
    palette = QApplication.instance().palette()  # type: ignore[union-attr]
    assert palette.color(QPalette.ColorRole.Window) == QColor("#202124")
    stored = gui.engine.call(lambda m: m.settings_store.all()).result(5)
    assert stored["theme"] == "dark" and stored["connections"] == 12
    qtbot.waitUntil(lambda: gui.window.categories[0].folder == "Movies", timeout=WAIT)
    limit = gui.engine.call(lambda m: (m.settings.connections, m.global_limiter.rate)).result(5)
    assert limit == (12, 512 * 1024)


def test_queues_dialog(qtbot, gui: GuiApp) -> None:
    dialog = gui.open_queues()
    qtbot.waitUntil(lambda: dialog.list.count() == 1, timeout=WAIT)
    dialog.max_concurrent.setValue(5)
    dialog.scheduled.setChecked(True)
    dialog.has_stop.setChecked(True)
    dialog.days[5].setChecked(False)
    dialog.days[6].setChecked(False)
    dialog.after.setCurrentIndex(dialog.after.findData("shutdown"))
    dialog.save_current()

    def saved() -> bool:
        queue = gui.engine.call(lambda m: m.queues.get(1)).result(5)
        return queue.max_concurrent == 5

    qtbot.waitUntil(saved, timeout=WAIT)
    queue = gui.engine.call(lambda m: m.queues.get(1)).result(5)
    assert (queue.start_time, queue.stop_time, queue.days) == ("01:00", "06:00", 0b0011111)
    assert queue.after_action is AfterAction.SHUTDOWN
    assert not dialog.delete_button.isEnabled()  # Main cannot be deleted
    dialog.accept()


def test_first_run_wizard(qtbot, gui: GuiApp, tmp_path) -> None:
    wizard = FirstRunWizard(dataclasses.replace(gui.settings, first_run_done=False))
    qtbot.addWidget(wizard)
    wizard.download_page.edit.setText(str(tmp_path / "E-drive-downloads"))
    assert "Free space" in wizard.download_page.space.text()
    result = wizard.result_settings()
    assert result.first_run_done and result.download_dir == tmp_path / "E-drive-downloads"


def test_countdown_cancel_and_expire(qtbot, gui: GuiApp) -> None:
    gui.client.powerRequested.emit(PowerRequested(AfterAction.SHUTDOWN, "Night"))
    assert gui.countdown is not None and "Night" in gui.countdown.label.text()
    gui.countdown.cancel_button.click()
    qtbot.wait(2500)
    assert gui.power_calls == []
    gui.client.powerRequested.emit(PowerRequested(AfterAction.SLEEP, "Night"))
    qtbot.waitUntil(lambda: gui.power_calls == [AfterAction.SLEEP], timeout=5000)


def test_cli_over_ipc_adds_to_the_app(qtbot, gui: GuiApp, server: FaultServer, tmp_path) -> None:
    url = server.url("/file/cli.zip?size=1000")
    added = in_thread(qtbot, lambda: client.request("add", {"url": url}))
    assert added["name"] == "cli.zip"
    wait_state(qtbot, gui.window, "cli.zip", JobState.COMPLETED)
    assert (tmp_path / "dl" / "Compressed" / "cli.zip").exists()
    listed = in_thread(qtbot, lambda: client.request("list"))
    assert [j["name"] for j in listed] == ["cli.zip"]


def test_activate_opens_start_dialog(qtbot, gui: GuiApp, server: FaultServer) -> None:
    url = server.url("/file/act.bin?size=10")
    in_thread(qtbot, lambda: client.request("activate", {"urls": [url]}))
    from opendm.gui.dialogs.start_download import StartDownloadDialog

    qtbot.waitUntil(
        lambda: any(isinstance(w, StartDownloadDialog) and w.isVisible()
                    for w in QApplication.topLevelWidgets()),
        timeout=WAIT,
    )  # fmt: skip


def test_second_launch_forwards_links(qtbot, gui: GuiApp) -> None:
    from opendm.gui import app as app_module

    lock = InstanceLock(os.environ["OPENDM_IPC_NAME"])
    assert lock.acquire()  # this test process plays the running instance
    try:
        seen: list[list[str]] = []
        gui.window.add_urls = lambda urls, **kw: seen.append(urls)  # type: ignore[method-assign]
        code = in_thread(qtbot, lambda: app_module.main(["https://example.com/x.zip", "junk"]))
        assert code == 0
        qtbot.waitUntil(lambda: seen == [["https://example.com/x.zip"]], timeout=WAIT)
    finally:
        lock.release()


def test_drag_and_drop_links_and_text_files(gui: GuiApp, tmp_path) -> None:
    links = tmp_path / "links.txt"
    links.write_text("# list\nhttps://example.com/a.zip\nhttps://example.com/b[1-2].bin\n")
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/c.iso"), QUrl.fromLocalFile(str(links))])
    assert gui.window.urls_from_drop(mime) == [
        "https://example.com/c.iso", "https://example.com/a.zip",
        "https://example.com/b1.bin", "https://example.com/b2.bin",
    ]  # fmt: skip
    text = QMimeData()
    text.setText("https://example.com/d.pdf")
    assert gui.window.urls_from_drop(text) == ["https://example.com/d.pdf"]


def test_clipboard_monitor(qtbot, gui: GuiApp) -> None:
    gui.clipboard.enabled = True
    clipboard = QApplication.clipboard()
    with qtbot.waitSignal(gui.clipboard.linkCopied, timeout=5000) as blocker:
        clipboard.setText("https://example.com/movie.mkv")
    assert blocker.args == ["https://example.com/movie.mkv"]
    with qtbot.assertNotEmitted(gui.clipboard.linkCopied, wait=300):
        clipboard.setText("https://example.com/page.html")  # not a known download type


def test_close_goes_to_tray_when_available(qtbot, gui: GuiApp) -> None:
    gui.window.tray_available = True
    gui.window.close()
    assert not gui.window.isVisible()
    assert gui.engine.thread is not None and gui.engine.thread.is_alive()
    gui.show_window()
    assert gui.window.isVisible()


def test_name_column_gets_the_space(qtbot, gui: GuiApp, server: FaultServer) -> None:
    # Regression (manual checklist): at the default window size the name was squeezed to
    # "t...p" and a horizontal scrollbar pushed "Added" out of view.
    from opendm.gui.models.downloads import NAME

    gui.window.add_urls([server.url("/file/test-pack.zip?size=1000")], ask=False)
    wait_state(qtbot, gui.window, "test-pack.zip", JobState.COMPLETED)
    gui.window.resize(1000, 600)
    qtbot.wait(100)
    header = gui.window.table.horizontalHeader()
    assert header.sectionSize(NAME) >= 150
    assert not gui.window.table.horizontalScrollBar().isVisible()


def test_wizard_warns_about_a_nearly_full_drive(qtbot, gui: GuiApp, tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from opendm.gui.dialogs import wizard as wizard_module

    free = {"bytes": 5 * 1024**3}
    monkeypatch.setattr(
        wizard_module.shutil, "disk_usage", lambda p: SimpleNamespace(free=free["bytes"])
    )
    wizard = FirstRunWizard(dataclasses.replace(gui.settings, first_run_done=False))
    qtbot.addWidget(wizard)
    page = wizard.download_page
    assert page.low_space and "nearly full" in page.space.text()
    free["bytes"] = 200 * 1024**3
    page.edit.setText(str(tmp_path / "D-drive"))
    assert not page.low_space and "nearly full" not in page.space.text()
