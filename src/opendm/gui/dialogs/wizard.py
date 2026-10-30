"""First-run wizard: download folder, browser extension, update checks."""

import dataclasses
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from opendm.core.app_settings import AppSettings
from opendm.core.units import format_bytes

LOW_SPACE = 30 * 1024**3  # warn below 30 GiB free: downloads can be large


def free_space(folder: Path) -> int | None:
    """Free bytes on the drive holding ``folder`` (or its nearest existing parent)."""
    probe = folder
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def free_space_text(folder: Path) -> str:
    free = free_space(folder)
    return "?" if free is None else format_bytes(free)


class _FolderPage(QWizardPage):
    def __init__(self, title: str, text: str, folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(title)
        intro = QLabel(text)
        intro.setWordWrap(True)
        self.edit = QLineEdit(str(folder))
        self.space = QLabel()
        self.space.setWordWrap(True)
        self.low_space = False
        browse = QPushButton(self.tr("Browse..."))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.edit)
        row.addWidget(browse)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(row)
        layout.addWidget(self.space)
        self.edit.textChanged.connect(self._update_space)
        self._update_space()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.title(), self.edit.text())
        if folder:
            self.edit.setText(folder)

    def _update_space(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        free = free_space(Path(text))
        message = self.tr("Free space there: {0}").format(free_space_text(Path(text)))
        self.low_space = free is not None and free < LOW_SPACE
        if self.low_space:
            message += self.tr(
                " - this drive is nearly full. Choose a folder on a drive with more space."
            )
        self.space.setText(message)
        self.space.setStyleSheet("color: #d35400; font-weight: bold" if self.low_space else "")

    def isComplete(self) -> bool:
        return bool(self.edit.text().strip())

    def folder(self) -> Path:
        return Path(self.edit.text().strip())


class FirstRunWizard(QWizard):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Welcome to OpenDM"))
        self._settings = settings
        self.download_page = _FolderPage(
            self.tr("Where should downloads go?"),
            self.tr("Files are sorted into Video, Audio, Documents, Compressed and Programs "
                    "folders inside this folder. If your C: drive is nearly full, choose a "
                    "folder on another drive (for example D: or E:)."),
            settings.download_dir,
        )  # fmt: skip
        # Helper tools (yt-dlp, FFmpeg) get their own folder next to OpenDM (D66): no question.
        browser = QWizardPage()
        browser.setTitle(self.tr("Browser integration"))
        note = QLabel(self.tr(
            "The OpenDM extension for Chrome and Edge sends downloads and videos from the "
            "browser to OpenDM. To set it up, open Settings -> Browser. You can also copy a "
            "link and use Add URL, or drag links onto the window."
        ))  # fmt: skip
        note.setWordWrap(True)
        QVBoxLayout(browser).addWidget(note)
        updates = QWizardPage()
        updates.setTitle(self.tr("Updates"))
        updates_note = QLabel(self.tr(
            "OpenDM never contacts the internet on its own unless you allow it here. You can "
            "change both later in Settings."
        ))  # fmt: skip
        updates_note.setWordWrap(True)
        self.update_check = QCheckBox(self.tr("Check for a new OpenDM when it starts"))
        self.tool_update_check = QCheckBox(
            self.tr("Check weekly for a new yt-dlp (video downloads need it up to date)")
        )
        self.update_check.setChecked(settings.update_check)
        self.tool_update_check.setChecked(settings.tool_update_check)
        box = QVBoxLayout(updates)
        for widget in (updates_note, self.update_check, self.tool_update_check):
            box.addWidget(widget)
        self.addPage(self.download_page)
        self.addPage(browser)
        self.addPage(updates)

    def result_settings(self) -> AppSettings:
        return dataclasses.replace(
            self._settings,
            download_dir=self.download_page.folder(),
            update_check=self.update_check.isChecked(),
            tool_update_check=self.tool_update_check.isChecked(),
            first_run_done=True,
        )
