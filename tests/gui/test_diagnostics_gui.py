"""Settings -> General -> Export diagnostics (spec 6.11, M9)."""

import json
import zipfile
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from opendm import __version__
from tests.gui.conftest import GuiApp


def test_export_diagnostics_button(qtbot, gui: GuiApp, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "out" / "diag.zip"
    shown: list[str] = []
    monkeypatch.setattr(
        "opendm.gui.dialogs.settings.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(target), "ZIP files (*.zip)"),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda p, t, text, *a, **k: shown.append(text))
    dialog = gui.open_settings()
    qtbot.addWidget(dialog)
    dialog.export_button.click()
    qtbot.waitUntil(lambda: bool(shown), timeout=15_000)
    assert str(target) in shown[0]
    with zipfile.ZipFile(target) as z:
        about = json.loads(z.read("about.json"))
        settings = json.loads(z.read("settings.json"))
    assert about["version"] == __version__ and "tools" in about
    assert settings["download_dir"] == str(gui.settings.download_dir)
    dialog.reject()


def test_export_cancelled_writes_nothing(qtbot, gui: GuiApp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "opendm.gui.dialogs.settings.QFileDialog.getSaveFileName", lambda *a, **k: ("", "")
    )
    dialog = gui.open_settings()
    qtbot.addWidget(dialog)
    dialog.export_button.click()
    qtbot.wait(300)
    assert not list(tmp_path.rglob("*.zip"))
    dialog.reject()
