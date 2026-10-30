"""Download-start dialog: probes the link, then lets the user confirm name, folder, etc."""

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opendm.core.checksum import parse_checksum
from opendm.core.filenames import sanitize_filename
from opendm.core.models import MAIN_QUEUE_ID, Category, DownloadRequest, ProbeResult, Queue
from opendm.core.redact import redact_url
from opendm.core.units import format_bytes
from opendm.discovery.categories import category_folder, match_category
from opendm.discovery.classify import LinkKind, classify
from opendm.engine.http.naming import filename_from_url
from opendm.gui.engine_client import EngineClient


@dataclass
class StartChoice:
    request: DownloadRequest
    category_id: int | None
    queue_id: int
    start: bool


class StartDownloadDialog(QDialog):
    mediaDetected = Signal(object)  # DownloadRequest: the link is a page or stream, not a file

    def __init__(
        self,
        client: EngineClient,
        request: DownloadRequest,
        *,
        base_dir: Path,
        categories: list[Category],
        queues: list[Queue],
        parent: QWidget | None = None,
        detect_media: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Start download"))
        self._detect_media = detect_media
        self.resize(600, 300)
        self._client = client
        self._request = request
        self._base = base_dir
        self._categories = categories
        self._folder_edited = False
        self.choice: StartChoice | None = None
        self.probe_result: ProbeResult | None = None

        self.url_label = QLabel(redact_url(request.url))
        self.url_label.setWordWrap(True)
        self.name_edit = QLineEdit(request.filename or filename_from_url(request.url) or "")
        self.size_label = QLabel(self.tr("checking..."))
        self.category_box = QComboBox()
        for category in categories:
            self.category_box.addItem(category.name, category.id)
        self.folder_edit = QLineEdit()
        browse = QPushButton(self.tr("Browse..."))
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit)
        folder_row.addWidget(browse)
        self.queue_box = QComboBox()
        for queue in queues:
            self.queue_box.addItem(queue.name, queue.id)
        self.checksum_edit = QLineEdit(request.checksum or "")
        self.checksum_edit.setPlaceholderText(self.tr("optional, e.g. sha256:..."))
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #c0392b")

        form = QFormLayout()
        form.addRow(self.tr("Link:"), self.url_label)
        form.addRow(self.tr("File name:"), self.name_edit)
        form.addRow(self.tr("Size:"), self.size_label)
        form.addRow(self.tr("Category:"), self.category_box)
        form.addRow(self.tr("Save to:"), folder_row)
        form.addRow(self.tr("Queue:"), self.queue_box)
        form.addRow(self.tr("Checksum:"), self.checksum_edit)

        self.buttons = QDialogButtonBox()
        self.start_button = self.buttons.addButton(
            self.tr("Start now"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.queue_button = self.buttons.addButton(
            self.tr("Add to queue"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.start_button.clicked.connect(lambda: self._finish(start=True))
        self.queue_button.clicked.connect(lambda: self._finish(start=False))
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

        self.folder_edit.textEdited.connect(self._mark_folder_edited)
        self.category_box.currentIndexChanged.connect(self._category_changed)
        self.name_edit.textChanged.connect(self._name_changed)
        self._name_changed()
        client.call(lambda m: m.probe(request), on_done=self._probed, on_error=self._probe_failed)

    # --- probe -----------------------------------------------------------------------------------

    def _probed(self, result: ProbeResult) -> None:
        self.probe_result = result
        is_file = classify(result.final_url, result.content_type) is LinkKind.FILE
        if self._detect_media and not is_file:
            # A web page or a stream: hand it to the video/audio flow instead.
            self.reject()
            self.mediaDetected.emit(self._request)
            return
        if not self._request.filename:
            self.name_edit.setText(result.filename)
        self.size_label.setText(
            format_bytes(result.size) if result.size is not None else self.tr("unknown")
        )

    def _probe_failed(self, error: BaseException) -> None:
        self.size_label.setText(self.tr("unknown"))
        message = getattr(error, "message", None) or str(error)
        self.error_label.setText(self.tr("Could not check the link: {0}").format(message))

    # --- fields ----------------------------------------------------------------------------------

    def _mark_folder_edited(self) -> None:
        self._folder_edited = True

    def _name_changed(self) -> None:
        category = match_category(self.name_edit.text(), self._categories)
        index = self.category_box.findData(category.id)
        if index >= 0 and index != self.category_box.currentIndex():
            self.category_box.setCurrentIndex(index)
        else:
            self._category_changed()

    def _category_changed(self) -> None:
        if self._folder_edited:
            return
        category_id = self.category_box.currentData()
        category = next((c for c in self._categories if c.id == category_id), None)
        if category is not None:
            self.folder_edit.setText(str(category_folder(category, self._base)))

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Save to"), self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self._folder_edited = True

    def _finish(self, start: bool) -> None:
        checksum = self.checksum_edit.text().strip() or None
        if checksum:
            try:
                parse_checksum(checksum)
            except ValueError as exc:
                self.error_label.setText(str(exc))
                return
        folder = self.folder_edit.text().strip()
        if not folder:
            self.error_label.setText(self.tr("Choose a folder."))
            return
        name = sanitize_filename(self.name_edit.text(), default="") or None
        request = replace(self._request, dest_dir=Path(folder), filename=name, checksum=checksum)
        self.choice = StartChoice(
            request,
            self.category_box.currentData(),
            self.queue_box.currentData() or MAIN_QUEUE_ID,
            start,
        )
        self.accept()
