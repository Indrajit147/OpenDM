"""A newer OpenDM is out: release notes, then Install / Skip this version / Later (spec 6.9)."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from opendm.core.units import format_bytes
from opendm.updater.github_releases import AppUpdate


class UpdateDialog(QDialog):
    installRequested = Signal()
    skipRequested = Signal()
    pageRequested = Signal()
    progressed = Signal(int, object)  # done, total (emitted from the engine thread)

    def __init__(
        self, update: AppUpdate, current: str, *, portable: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("OpenDM update"))
        self.resize(560, 420)
        self.update_info = update
        self.heading = QLabel(
            self.tr("<b>OpenDM {0} is available.</b> You have {1}.").format(update.version, current)
        )
        self.heading.setWordWrap(True)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        if update.notes_format == "html":  # from the releases feed (GitHub rendered it)
            self.notes.setHtml(update.notes or self.tr("No release notes."))
        else:
            self.notes.setMarkdown(update.notes or self.tr("No release notes."))
        size = update.installer.size if update.installer else None
        if portable:
            hint = self.tr(
                "This is the portable version: download the new ZIP from the release page "
                "and unzip it over this folder (your data folder is kept)."
            )
        else:
            hint = self.tr("Install downloads the installer{0}, checks its SHA-256 and runs it "
                           "after OpenDM closes. Your settings and downloads are kept.").format(
                f" ({format_bytes(size)})" if size else ""
            )  # fmt: skip
        self.hint = QLabel(hint)
        self.hint.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.status = QLabel()
        self.status.setVisible(False)

        self.install_button = QPushButton(self.tr("Install"))
        self.install_button.setDefault(True)
        self.install_button.setVisible(not portable and update.installer is not None)
        self.page_button = QPushButton(self.tr("Open release page"))
        self.skip_button = QPushButton(self.tr("Skip this version"))
        self.later_button = QPushButton(self.tr("Later"))
        self.install_button.clicked.connect(self.installRequested.emit)
        self.page_button.clicked.connect(self.pageRequested.emit)
        self.skip_button.clicked.connect(self.skipRequested.emit)
        self.skip_button.clicked.connect(self.reject)
        self.later_button.clicked.connect(self.reject)
        self.progressed.connect(self._show_progress)

        buttons = QHBoxLayout()
        buttons.addWidget(self.page_button)
        buttons.addStretch()
        for button in (self.skip_button, self.later_button, self.install_button):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.notes)
        layout.addWidget(self.hint)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def set_busy(self, text: str) -> None:
        for button in (self.install_button, self.skip_button):
            button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.setText(text)
        self.status.setVisible(True)

    def set_idle(self) -> None:
        for button in (self.install_button, self.skip_button):
            button.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setVisible(False)

    def _show_progress(self, done: int, total: int | None) -> None:
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
        self.status.setText(
            self.tr("Downloading the installer: {0}").format(
                f"{format_bytes(done)} / {format_bytes(total)}" if total else format_bytes(done)
            )
        )
