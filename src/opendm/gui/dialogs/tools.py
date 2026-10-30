"""Consent before downloading yt-dlp/FFmpeg (spec 6.8), and install progress."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opendm.core.units import format_bytes
from opendm.gui.dialogs.wizard import free_space_text
from opendm.tools.sources import FFMPEG_HOME, YTDLP_HOME

if TYPE_CHECKING:
    from opendm.gui.engine_client import EngineClient

TOOL_TEXT = {
    "yt-dlp": ("yt-dlp", "finds and downloads video and audio from web pages", YTDLP_HOME),
    "ffmpeg": ("FFmpeg", "joins video and audio and converts formats", FFMPEG_HOME),
}


class ToolsConsentDialog(QDialog):
    """Lists what will be downloaded, from where, how big, and lets the user pick the folder."""

    def __init__(
        self,
        missing: list[str],
        folder: Path,
        sizes: dict[str, int | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Download helper tools?"))
        self.missing = missing
        intro = QLabel(self.tr(
            "Downloading video and audio needs free helper programs that OpenDM does not "
            "include. They are downloaded from their official sources and checked against "
            "their published SHA-256 checksums. Nothing is downloaded unless you agree."
        ))  # fmt: skip
        intro.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        for tool in missing:
            name, purpose, home = TOOL_TEXT[tool]
            size = (sizes or {}).get(tool)
            size_text = format_bytes(size) if size else self.tr("size unknown")
            label = QLabel(f"<b>{name}</b> ({size_text}): {purpose}.<br>"
                           f"<a href='{home}'>{home}</a>")  # fmt: skip
            label.setOpenExternalLinks(True)
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addWidget(QLabel(self.tr("Save the tools in:")))
        self.folder_edit = QLineEdit(str(folder))
        browse = QPushButton(self.tr("Browse..."))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder_edit)
        row.addWidget(browse)
        layout.addLayout(row)
        self.space = QLabel()
        layout.addWidget(self.space)
        buttons = QDialogButtonBox()
        self.download_button = buttons.addButton(
            self.tr("Download"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.folder_edit.textChanged.connect(self._update_space)
        self._update_space()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Tools folder"), self.folder_edit.text()
        )
        if folder:
            self.folder_edit.setText(folder)

    def _update_space(self) -> None:
        text = self.folder_edit.text().strip()
        self.download_button.setEnabled(bool(text))
        if text:
            self.space.setText(self.tr("Free space there: {0}").format(free_space_text(Path(text))))

    def folder(self) -> Path:
        return Path(self.folder_edit.text().strip())


class ToolProgressDialog(QDialog):
    """Shows tool downloads; closed by the caller when the installs finish."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Downloading tools"))
        self.setMinimumWidth(420)
        self.label = QLabel(self.tr("Starting..."))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)

    def show_progress(self, tool: str, done: int, total: int | None) -> None:
        name = TOOL_TEXT.get(tool, (tool,))[0]
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            self.label.setText(
                self.tr("{0}: {1} of {2}").format(name, format_bytes(done), format_bytes(total))
            )
        else:
            self.bar.setRange(0, 0)
            self.label.setText(self.tr("{0}: {1}").format(name, format_bytes(done)))

    def show_step(self, text: str) -> None:
        self.bar.setRange(0, 0)
        self.label.setText(text)


class ToolsPanel(QWidget):
    """Settings -> Tools: where the tools are, their versions, install/update/use existing."""

    def __init__(
        self,
        client: "EngineClient",
        *,
        on_install: "Callable[[list[str]], None]",
        on_existing: "Callable[[str, Path], None]",
        update_check: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._on_install = on_install
        self._on_existing = on_existing
        layout = QVBoxLayout(self)
        self.labels: dict[str, QLabel] = {}
        for tool in ("yt-dlp", "ffmpeg"):
            name, purpose, _ = TOOL_TEXT[tool]
            box = QVBoxLayout()
            title = QLabel(f"<b>{name}</b> - {purpose}")
            status = QLabel(self.tr("checking..."))
            status.setWordWrap(True)
            status.setTextInteractionFlags(
                status.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.labels[tool] = status
            install = QPushButton(self.tr("Download / update"))
            install.clicked.connect(lambda _=False, t=tool: self._on_install([t]))
            existing = QPushButton(self.tr("Use existing..."))
            existing.clicked.connect(lambda _=False, t=tool: self._pick_existing(t))
            row = QHBoxLayout()
            row.addWidget(install)
            row.addWidget(existing)
            row.addStretch()
            box.addWidget(title)
            box.addWidget(status)
            box.addLayout(row)
            layout.addLayout(box)
        self.update_check = QCheckBox(self.tr("Check for yt-dlp updates once a week"))
        self.update_check.setChecked(update_check)
        self.check_now = QPushButton(self.tr("Check for yt-dlp update now"))
        self.check_now.clicked.connect(self.check_update)
        self.update_label = QLabel()
        layout.addWidget(self.update_check)
        layout.addWidget(self.check_now)
        layout.addWidget(self.update_label)
        layout.addStretch()
        self.refresh()

    def refresh(self) -> None:
        self._client.call(lambda m: m.tool_status(), on_done=self._show, on_error=lambda e: None)

    def _show(self, infos: list) -> None:
        for info in infos:
            label = self.labels.get(info.name)
            if label is None:
                continue
            if info.installed:
                label.setText(self.tr("{0}\n{1}").format(info.version, info.path))
            else:
                label.setText(self.tr("Not installed (expected at {0})").format(info.path))

    def _pick_existing(self, tool: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Choose {0}").format(TOOL_TEXT[tool][0]), "", "Programs (*.exe)"
        )
        if path:
            self._on_existing(tool, Path(path))

    def check_update(self) -> None:
        self.update_label.setText(self.tr("Checking..."))

        def done(result) -> None:
            if result is None:
                self.update_label.setText(self.tr("yt-dlp is up to date."))
            else:
                current, latest = result
                self.update_label.setText(
                    self.tr("Update available: {0} -> {1}. Click Download / update.").format(
                        current or self.tr("not installed"), latest
                    )
                )

        self._client.call(
            lambda m: m.check_ytdlp_update(), on_done=done,
            on_error=lambda e: self.update_label.setText(self.tr("Check failed: {0}").format(e)),
        )  # fmt: skip
