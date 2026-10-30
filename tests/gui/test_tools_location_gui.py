"""The tools folder in the GUI: refused inside Downloads, moved out on start (M8)."""

import dataclasses
from pathlib import Path

from PySide6.QtWidgets import QDialog

from opendm.gui.dialogs.tools import ToolsConsentDialog
from opendm.tools.location import tools_dir_problem


def test_consent_dialog_refuses_a_folder_in_downloads(qtbot, tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    dialog = ToolsConsentDialog(
        ["yt-dlp"], tmp_path / "tools", parent=None,
        check=lambda folder: tools_dir_problem(folder, downloads),
    )  # fmt: skip
    qtbot.addWidget(dialog)
    assert dialog.download_button.isEnabled() and not dialog.problem.text()
    dialog.folder_edit.setText(str(downloads))
    assert not dialog.download_button.isEnabled()
    assert "outside your download folder" in dialog.problem.text()
    dialog.folder_edit.setText(str(tmp_path / "Tools"))
    assert dialog.download_button.isEnabled() and not dialog.problem.text()


def test_settings_refuse_a_tools_folder_in_downloads(qtbot, gui, monkeypatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "opendm.gui.dialogs.settings.QMessageBox.warning",
        lambda parent, title, text: warnings.append(text),
    )
    dialog = gui.open_settings()
    qtbot.addWidget(dialog)
    dialog.tools_dir.setText(str(Path(dialog.download_dir.text()) / "tools"))
    dialog.accept()
    assert warnings and "outside your download folder" in warnings[0]
    assert dialog.isVisible() and dialog.result() != QDialog.DialogCode.Accepted
    dialog.tools_dir.setText(str(gui.settings.tools_dir))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_tools_in_the_download_folder_are_moved_on_start(qtbot, gui, tmp_path: Path) -> None:
    downloads = gui.settings.download_dir
    old_tool = downloads / "yt-dlp" / "yt-dlp.exe"
    old_tool.parent.mkdir(parents=True)
    old_tool.write_bytes(b"ytdlp")
    (downloads / "song.mp3").write_bytes(b"music")
    default = gui.default_tools_dir
    gui.save_settings(dataclasses.replace(
        gui.settings, tools_dir=downloads, ytdlp_path=str(old_tool)
    ))  # fmt: skip
    notes: list[str] = []
    gui.notify = lambda title, text: notes.append(text)  # type: ignore[method-assign]
    relocate(qtbot, gui)
    assert gui.settings.tools_dir == default
    assert (default / "yt-dlp" / "yt-dlp.exe").read_bytes() == b"ytdlp"
    assert gui.settings.ytdlp_path == str(default / "yt-dlp" / "yt-dlp.exe")
    assert (downloads / "song.mp3").exists() and not old_tool.exists()
    assert notes and str(default) in notes[0]
    stored = gui.client.call(lambda m: m.settings_store.all()).result(5)  # type: ignore[union-attr]
    assert stored["tools_dir"] == str(default)


def test_nothing_happens_when_the_tools_folder_is_fine(qtbot, gui) -> None:
    before = gui.settings
    relocate(qtbot, gui)
    assert gui.settings == before


def test_settings_default_tools_folder_is_not_in_downloads(gui) -> None:
    assert tools_dir_problem(gui.settings.tools_dir, gui.settings.download_dir) is None
    assert gui.settings.tools_dir == gui.default_tools_dir


def test_tools_in_the_old_default_follow_the_new_default(qtbot, gui, tmp_path: Path) -> None:
    old = gui.data_dir / "tools"  # 0.7's default, on C:
    (old / "ffmpeg" / "bin").mkdir(parents=True)
    (old / "ffmpeg" / "bin" / "ffmpeg.exe").write_bytes(b"ffmpeg")
    gui.default_tools_dir = tmp_path / "Program" / "tools"  # as if installed on another drive
    gui.save_settings(dataclasses.replace(gui.settings, tools_dir=old))
    relocate(qtbot, gui)
    assert gui.settings.tools_dir == tmp_path / "Program" / "tools"
    assert (tmp_path / "Program" / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe").exists()


def test_a_folder_the_user_chose_stays(qtbot, gui, tmp_path: Path) -> None:
    chosen = tmp_path / "MyTools"
    gui.save_settings(dataclasses.replace(gui.settings, tools_dir=chosen))
    gui.default_tools_dir = tmp_path / "Program" / "tools"
    relocate(qtbot, gui)
    assert gui.settings.tools_dir == chosen


def relocate(qtbot, gui) -> None:
    gui.relocate_tools_if_needed()
    qtbot.waitUntil(lambda: not gui.tools_moving, timeout=10_000)


def test_moving_does_not_block_the_window(qtbot, gui, monkeypatch) -> None:
    import time

    def slow_move(old: Path, new: Path) -> list[str]:
        time.sleep(1.0)
        return []

    monkeypatch.setattr("opendm.gui.app.relocate_tools", slow_move)
    gui.save_settings(dataclasses.replace(gui.settings, tools_dir=gui.settings.download_dir))
    started = time.perf_counter()
    gui.relocate_tools_if_needed()
    assert time.perf_counter() - started < 0.3 and gui.tools_moving
    qtbot.waitUntil(lambda: not gui.tools_moving, timeout=10_000)
    assert gui.settings.tools_dir == gui.default_tools_dir
