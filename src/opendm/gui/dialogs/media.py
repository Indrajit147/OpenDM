"""Quality picker for video/audio pages (spec 6.2)."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opendm.core.models import MAIN_QUEUE_ID, Category, Queue
from opendm.core.units import format_duration
from opendm.discovery.categories import category_folder, match_category
from opendm.engine.media.formats import CONTAINERS, MediaOptions
from opendm.engine.media.ytdlp import MediaEntry, MediaInfo


@dataclass
class MediaChoice:
    entries: list[MediaEntry]
    options: MediaOptions
    folder: Path
    queue_id: int
    start: bool
    category_id: int | None


class MediaDialog(QDialog):
    wholePlaylistRequested = Signal()  # the link was one video of a playlist: show them all

    def __init__(
        self,
        info: MediaInfo,
        *,
        base_dir: Path,
        categories: list[Category],
        queues: list[Queue],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Download video or audio"))
        self.resize(560, 480 if info.is_playlist else 360)
        self.info = info
        self._base = base_dir
        self._categories = categories
        self._folder_edited = False
        self.choice: MediaChoice | None = None

        title = QLabel(f"<b>{_escape(info.title)}</b>")
        title.setWordWrap(True)
        details = []
        if info.uploader:
            details.append(info.uploader)
        if info.duration:
            details.append(format_duration(info.duration))
        if info.is_playlist:
            details.append(self.tr("{0} items").format(len(info.entries)))
        subtitle = QLabel(" - ".join(details))
        subtitle.setVisible(bool(details))

        self.quality = QComboBox()
        self.quality.addItem(self.tr("Best available"), "best")
        for height in info.heights:
            if str(height) in ("2160", "1440", "1080", "720", "480", "360"):
                self.quality.addItem(f"{height}p", str(height))
        if info.is_playlist:  # entries may differ: offer the usual caps
            for height in ("1080", "720", "480"):
                self.quality.addItem(f"{height}p", height)
        self.quality.addItem(self.tr("Audio only (MP3)"), "audio-mp3")
        self.quality.addItem(self.tr("Audio only (M4A)"), "audio-m4a")
        self.container = QComboBox()
        for container in CONTAINERS:
            self.container.addItem(container.upper(), container)
        self.subtitles = QListWidget()
        self.subtitles.setMaximumHeight(90)
        for lang in info.subtitles:
            self._add_check(self.subtitles, lang, lang)
        for lang in info.auto_subtitles:
            if lang not in info.subtitles:
                self._add_check(
                    self.subtitles, self.tr("{0} (automatic)").format(lang), "auto:" + lang
                )
        self.embed_thumbnail = QCheckBox(self.tr("Embed the thumbnail in the file"))
        self.folder_edit = QLineEdit()
        self.folder_edit.textEdited.connect(self._mark_folder)
        browse = QPushButton(self.tr("Browse..."))
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(browse)
        self.queue_box = QComboBox()
        for queue in queues:
            self.queue_box.addItem(queue.name, queue.id)

        form = QFormLayout()
        form.addRow(self.tr("Quality:"), self.quality)
        form.addRow(self.tr("Format:"), self.container)
        if self.subtitles.count():
            form.addRow(self.tr("Subtitles:"), self.subtitles)
        form.addRow(self.embed_thumbnail)
        form.addRow(self.tr("Save to:"), folder_row)
        form.addRow(self.tr("Queue:"), self.queue_box)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.playlist_button = QPushButton(
            self.tr("This video is part of a playlist. Show the whole playlist...")
        )
        self.playlist_button.setVisible(info.playlist_url is not None)
        self.playlist_button.clicked.connect(self.wholePlaylistRequested.emit)
        layout.addWidget(self.playlist_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.entries = QListWidget()
        if info.is_playlist:
            for entry in info.entries:
                text = entry.title
                if entry.duration:
                    text += f"  ({format_duration(entry.duration)})"
                item = self._add_check(self.entries, text, entry.url)
                item.setCheckState(Qt.CheckState.Checked)
            toggles = QHBoxLayout()
            for label, state in ((self.tr("Select all"), Qt.CheckState.Checked),
                                 (self.tr("Select none"), Qt.CheckState.Unchecked)):  # fmt: skip
                button = QPushButton(label)
                button.clicked.connect(lambda _=False, s=state: self._set_all(s))
                toggles.addWidget(button)
            toggles.addStretch()
            layout.addWidget(QLabel(self.tr("Playlist items:")))
            layout.addWidget(self.entries)
            layout.addLayout(toggles)
            self.entries.itemChanged.connect(self._validate)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox()
        self.start_button = self.buttons.addButton(
            self.tr("Start now"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.queue_button = self.buttons.addButton(
            self.tr("Add to queue"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.start_button.clicked.connect(lambda: self._finish(True))
        self.queue_button.clicked.connect(lambda: self._finish(False))
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.quality.currentIndexChanged.connect(self._quality_changed)
        self._quality_changed()

    @staticmethod
    def _add_check(widget: QListWidget, text: str, data: str) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, data)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        widget.addItem(item)
        return item

    def _set_all(self, state: Qt.CheckState) -> None:
        for i in range(self.entries.count()):
            self.entries.item(i).setCheckState(state)

    def _checked(self, widget: QListWidget) -> list[str]:
        return [
            widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(widget.count())
            if widget.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _category(self) -> Category | None:
        audio = str(self.quality.currentData()).startswith("audio-")
        sample = "x.mp3" if audio else "x." + str(self.container.currentData())
        return match_category(sample, self._categories) if self._categories else None

    def _quality_changed(self) -> None:
        audio = str(self.quality.currentData()).startswith("audio-")
        self.container.setEnabled(not audio)
        if not self._folder_edited:
            category = self._category()
            folder = category_folder(category, self._base) if category else self._base
            self.folder_edit.setText(str(folder))
        self._validate()

    def _validate(self) -> None:
        ok = not self.info.is_playlist or bool(self._checked(self.entries))
        self.start_button.setEnabled(ok)
        self.queue_button.setEnabled(ok)

    def _mark_folder(self) -> None:
        self._folder_edited = True

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Save to"), self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self._folder_edited = True

    def options(self) -> MediaOptions:
        picked = self._checked(self.subtitles)
        manual = tuple(p for p in picked if not p.startswith("auto:"))
        auto = tuple(p.removeprefix("auto:") for p in picked if p.startswith("auto:"))
        return MediaOptions(
            quality=str(self.quality.currentData()),
            container=str(self.container.currentData()),
            subtitles=manual + auto,
            auto_subtitles=bool(auto),
            embed_thumbnail=self.embed_thumbnail.isChecked(),
        )

    def _finish(self, start: bool) -> None:
        if self.info.is_playlist:
            wanted = set(self._checked(self.entries))
            entries = [e for e in self.info.entries if e.url in wanted]
        else:
            entries = [MediaEntry(self.info.url, self.info.title, self.info.duration)]
        category = self._category()
        self.choice = MediaChoice(
            entries=entries,
            options=self.options(),
            folder=Path(self.folder_edit.text().strip() or self._base),
            queue_id=self.queue_box.currentData() or MAIN_QUEUE_ID,
            start=start,
            category_id=category.id if category else None,
        )
        self.accept()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
