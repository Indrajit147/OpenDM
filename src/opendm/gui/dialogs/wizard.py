"""First-run wizard: download folder, tools folder, browser extension notes."""

import dataclasses
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
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


def free_space_text(folder: Path) -> str:
    probe = folder
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return format_bytes(shutil.disk_usage(probe).free)
    except OSError:
        return "?"


class _FolderPage(QWizardPage):
    def __init__(self, title: str, text: str, folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle(title)
        intro = QLabel(text)
        intro.setWordWrap(True)
        self.edit = QLineEdit(str(folder))
        self.space = QLabel()
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
        if text:
            self.space.setText(self.tr("Free space there: {0}").format(free_space_text(Path(text))))

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
        self.tools_page = _FolderPage(
            self.tr("Where should helper tools go?"),
            self.tr("Later versions can download free tools (yt-dlp and FFmpeg) for video "
                    "downloads. Nothing is downloaded without asking you first."),
            settings.tools_dir,
        )  # fmt: skip
        browser = QWizardPage()
        browser.setTitle(self.tr("Browser integration"))
        note = QLabel(self.tr(
            "A Chrome and Edge extension that sends downloads to OpenDM will come in a later "
            "version. For now, copy a link and use Add URL, or drag links onto the window."
        ))  # fmt: skip
        note.setWordWrap(True)
        QVBoxLayout(browser).addWidget(note)
        self.addPage(self.download_page)
        self.addPage(self.tools_page)
        self.addPage(browser)

    def result_settings(self) -> AppSettings:
        return dataclasses.replace(
            self._settings,
            download_dir=self.download_page.folder(),
            tools_dir=self.tools_page.folder(),
            first_run_done=True,
        )
