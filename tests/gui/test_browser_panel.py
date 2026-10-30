"""Settings -> Browser: integration status, set up and remove (M7)."""

from pathlib import Path

from opendm.core.app_settings import AppSettings
from opendm.gui.dialogs.browser import BrowserPanel
from opendm.gui.dialogs.settings import SettingsDialog


class FakeRegistry:
    def __init__(self) -> None:
        self.registered: Path | None = None
        self.calls: list[str] = []

    def status(self) -> dict[str, Path | None]:
        return {"Chrome": self.registered, "Edge": self.registered}

    def register(self) -> Path:
        self.calls.append("register")
        self.registered = Path("D:/x/host.json")
        return self.registered

    def unregister(self) -> None:
        self.calls.append("unregister")
        self.registered = None


def make_panel(qtbot, tmp_path: Path, fake: FakeRegistry, opened: list[Path]) -> BrowserPanel:
    panel = BrowserPanel(
        status=fake.status, register=fake.register, unregister=fake.unregister,
        extension_dir=tmp_path / "extension", open_folder=opened.append,
    )  # fmt: skip
    qtbot.addWidget(panel)
    return panel


def test_set_up_and_remove(qtbot, tmp_path: Path) -> None:
    fake, opened = FakeRegistry(), []
    panel = make_panel(qtbot, tmp_path, fake, opened)
    assert "not set up" in panel.status_label.text()
    assert panel.setup_button.isEnabled() and not panel.remove_button.isEnabled()

    panel.setup_button.click()
    assert fake.calls == ["register"]
    assert "Chrome: set up" in panel.status_label.text()
    assert "Edge: set up" in panel.status_label.text()
    assert panel.remove_button.isEnabled()

    panel.remove_button.click()
    assert fake.calls == ["register", "unregister"]
    assert "not set up" in panel.status_label.text()


def test_failure_is_shown(qtbot, tmp_path: Path) -> None:
    fake, opened = FakeRegistry(), []

    def broken() -> Path:
        raise PermissionError("access denied")

    fake.register = broken  # type: ignore[method-assign]
    panel = make_panel(qtbot, tmp_path, fake, opened)
    panel.setup_button.click()
    assert "access denied" in panel.message.text()


def test_open_extension_folder(qtbot, tmp_path: Path) -> None:
    (tmp_path / "extension").mkdir()
    fake, opened = FakeRegistry(), []
    panel = make_panel(qtbot, tmp_path, fake, opened)
    assert str(tmp_path / "extension") in panel.instructions.text()
    panel.folder_button.click()
    assert opened == [tmp_path / "extension"]


def test_settings_dialog_has_the_browser_tab(qtbot, tmp_path: Path) -> None:
    fake, opened = FakeRegistry(), []
    panel = make_panel(qtbot, tmp_path, fake, opened)
    settings = AppSettings(download_dir=tmp_path / "dl", tools_dir=tmp_path / "tools")
    dialog = SettingsDialog(settings, [], browser_panel=panel)
    qtbot.addWidget(dialog)
    titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert dialog.tabs.widget(titles.index("Browser")).isAncestorOf(panel)
