"""Update check in the GUI: opt-in, dialog, skip, install after quit, portable (M8)."""

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from opendm import __version__
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.version import parse_version
from opendm.gui.dialogs.wizard import FirstRunWizard
from opendm.updater.github_releases import AppUpdate, Asset
from tests.gui.conftest import GuiApp

WAIT = 10_000
NEWER = AppUpdate(
    version=parse_version("99.0.0"), tag="v99.0.0", title="OpenDM 99.0.0",
    notes="### Added\n- Teleportation.", page_url="https://example.invalid/releases/v99.0.0",
    installer=Asset("OpenDM-99.0.0-setup.exe", "https://example.invalid/setup.exe", 26_000_000),
    portable=None, sums=Asset("SHA256SUMS.txt", "https://example.invalid/sums", 100),
)  # fmt: skip


class FakeUpdater:
    def __init__(self, update: AppUpdate | None = NEWER, fail: bool = False) -> None:
        self.update, self.fail = update, fail
        self.checks: list[tuple[str, bool]] = []
        self.downloads: list[Path] = []

    async def check(self, current: str, *, prereleases: bool) -> AppUpdate | None:
        self.checks.append((current, prereleases))
        return self.update

    async def download(self, update: AppUpdate, folder: Path, progress=None) -> Path:
        if self.fail:
            raise DownloadError(ErrorKind.CHECKSUM_MISMATCH, "does not match its SHA-256")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / update.installer.name  # type: ignore[union-attr]
        path.write_bytes(b"installer")
        if progress is not None:
            progress(9, 9)
        self.downloads.append(folder)
        return path


@pytest.fixture
def boxes(monkeypatch) -> list[str]:
    shown: list[str] = []
    for name in ("information", "warning"):
        monkeypatch.setattr(
            QMessageBox, name,
            lambda parent, title, text, *a, _n=name, **k: shown.append(f"{_n}: {text}"),
        )  # fmt: skip
    return shown


def use(gui: GuiApp, updater: FakeUpdater, **settings) -> FakeUpdater:
    gui.updater = updater  # type: ignore[assignment]
    gui.save_settings(dataclasses.replace(gui.settings, **settings))
    return updater


def test_no_check_unless_turned_on(qtbot, gui: GuiApp) -> None:
    updater = use(gui, FakeUpdater(), update_check=False)
    gui.check_app_update()
    qtbot.wait(300)
    assert updater.checks == [] and gui.update_dialog is None


def test_startup_check_shows_the_new_version(qtbot, gui: GuiApp) -> None:
    updater = use(gui, FakeUpdater(), update_check=True, include_prereleases=True)
    gui.check_app_update()
    qtbot.waitUntil(lambda: gui.update_dialog is not None, timeout=WAIT)
    assert updater.checks == [(__version__, True)]
    dialog = gui.update_dialog
    assert dialog is not None and "99.0.0" in dialog.heading.text()
    assert "Teleportation" in dialog.notes.toPlainText()
    assert dialog.install_button.isVisible() and dialog.install_button.isEnabled()


def test_skip_this_version(qtbot, gui: GuiApp) -> None:
    use(gui, FakeUpdater(), update_check=True)
    gui.check_app_update()
    qtbot.waitUntil(lambda: gui.update_dialog is not None, timeout=WAIT)
    gui.update_dialog.skip_button.click()  # type: ignore[union-attr]
    assert gui.settings.skipped_version == "99.0.0"
    gui.update_dialog = None
    gui.check_app_update()  # automatic: the skipped version stays quiet
    qtbot.wait(300)
    assert gui.update_dialog is None
    gui.check_app_update(manual=True)  # "Check now" still shows it
    qtbot.waitUntil(lambda: gui.update_dialog is not None, timeout=WAIT)


def test_manual_check_when_up_to_date(qtbot, gui: GuiApp, boxes) -> None:
    use(gui, FakeUpdater(update=None), update_check=False)
    gui.check_app_update(manual=True)
    qtbot.waitUntil(lambda: bool(boxes), timeout=WAIT)
    assert "latest version" in boxes[0] and __version__ in boxes[0]


def test_install_downloads_then_runs_after_quitting(qtbot, gui: GuiApp, monkeypatch) -> None:
    updater = use(gui, FakeUpdater(), update_check=True)
    quits: list[bool] = []
    monkeypatch.setattr(gui, "quit", lambda: quits.append(True))
    gui.check_app_update()
    qtbot.waitUntil(lambda: gui.update_dialog is not None, timeout=WAIT)
    gui.update_dialog.install_button.click()  # type: ignore[union-attr]
    qtbot.waitUntil(lambda: bool(quits), timeout=WAIT)
    assert updater.downloads == [gui.updates_dir]
    assert gui.run_after_quit == gui.updates_dir / "OpenDM-99.0.0-setup.exe"


def test_a_failed_download_runs_nothing(qtbot, gui: GuiApp, boxes, monkeypatch) -> None:
    use(gui, FakeUpdater(fail=True), update_check=True)
    quits: list[bool] = []
    monkeypatch.setattr(gui, "quit", lambda: quits.append(True))
    gui.check_app_update()
    qtbot.waitUntil(lambda: gui.update_dialog is not None, timeout=WAIT)
    gui.update_dialog.install_button.click()  # type: ignore[union-attr]
    qtbot.waitUntil(lambda: bool(boxes), timeout=WAIT)
    assert "SHA-256" in boxes[0]
    assert gui.run_after_quit is None and not quits


def test_portable_opens_the_release_page(qtbot, gui: GuiApp, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("opendm.gui.app.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toString()))  # fmt: skip
    use(gui, FakeUpdater(), update_check=True)
    gui.portable = True
    gui.check_app_update()
    qtbot.waitUntil(lambda: gui.update_dialog is not None, timeout=WAIT)
    dialog = gui.update_dialog
    assert dialog is not None and not dialog.install_button.isVisible()
    dialog.page_button.click()
    assert opened == [NEWER.page_url]


def test_errors_are_quiet_on_startup_but_shown_on_request(qtbot, gui: GuiApp, boxes) -> None:
    class Broken(FakeUpdater):
        async def check(self, current: str, *, prereleases: bool):
            raise DownloadError(ErrorKind.CONNECTION, "no internet")

    use(gui, Broken(), update_check=True)
    gui.check_app_update()
    qtbot.wait(300)
    assert boxes == []
    gui.check_app_update(manual=True)
    qtbot.waitUntil(lambda: bool(boxes), timeout=WAIT)
    assert "no internet" in boxes[0]


def test_settings_updates_tab(qtbot, gui: GuiApp, boxes) -> None:
    updater = use(gui, FakeUpdater(update=None))
    dialog = gui.open_settings()
    qtbot.addWidget(dialog)
    assert __version__ in dialog.version_label.text()
    dialog.update_check.setChecked(True)
    dialog.prereleases.setChecked(True)
    dialog.accept()
    assert gui.settings.update_check and gui.settings.include_prereleases
    dialog = gui.open_settings()
    qtbot.addWidget(dialog)
    dialog.check_now_button.click()
    qtbot.waitUntil(lambda: bool(updater.checks), timeout=WAIT)
    dialog.reject()


def test_wizard_asks_about_updates_but_not_about_tools(qtbot, gui: GuiApp) -> None:
    wizard = FirstRunWizard(dataclasses.replace(gui.settings, first_run_done=False))
    qtbot.addWidget(wizard)
    assert not hasattr(wizard, "tools_page")
    assert not wizard.update_check.isChecked() and not wizard.tool_update_check.isChecked()
    wizard.update_check.setChecked(True)
    result = wizard.result_settings()
    assert result.update_check and not result.tool_update_check
    assert result.tools_dir == gui.settings.tools_dir


def test_old_installers_are_cleaned_on_start(qtbot, gui: GuiApp) -> None:
    gui.updates_dir.mkdir(parents=True, exist_ok=True)
    (gui.updates_dir / "OpenDM-0.1.0-setup.exe").write_bytes(b"old")
    gui.start(wizard=False)
    assert not (gui.updates_dir / "OpenDM-0.1.0-setup.exe").exists()
