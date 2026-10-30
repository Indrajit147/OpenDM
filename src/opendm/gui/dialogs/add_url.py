"""Add URL dialog: one link, or many (with ``[1-20]`` patterns) in batch mode."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opendm.core.batch import parse_url_list


class AddUrlDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, text: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Add download"))
        self.resize(560, 300)
        self.tabs = QTabWidget()
        single = QWidget()
        single_layout = QVBoxLayout(single)
        single_layout.addWidget(QLabel(self.tr("Link (http or https):")))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/file.zip")
        single_layout.addWidget(self.url_edit)
        single_layout.addStretch()
        batch = QWidget()
        batch_layout = QVBoxLayout(batch)
        batch_layout.addWidget(
            QLabel(self.tr("One link per line. Patterns like file[01-20].zip are expanded."))
        )
        self.batch_edit = QPlainTextEdit()
        batch_layout.addWidget(self.batch_edit)
        self.batch_status = QLabel()
        batch_layout.addWidget(self.batch_status)
        self.tabs.addTab(single, self.tr("Single"))
        self.tabs.addTab(batch, self.tr("Batch"))
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.buttons)
        self.url_edit.textChanged.connect(self._validate)
        self.batch_edit.textChanged.connect(self._validate)
        self.tabs.currentChanged.connect(self._validate)
        self._prefill(text if text is not None else QGuiApplication.clipboard().text())
        self._validate()

    def _prefill(self, text: str) -> None:
        urls, _ = parse_url_list(text or "")
        if len(urls) == 1 and "[" not in text:
            self.url_edit.setText(urls[0])
        elif len(urls) > 1:
            self.batch_edit.setPlainText(text.strip())
            self.tabs.setCurrentIndex(1)

    def urls(self) -> list[str]:
        if self.tabs.currentIndex() == 0:
            found, _ = parse_url_list(self.url_edit.text())
            return found[:1] if "[" not in self.url_edit.text() else found
        found, _ = parse_url_list(self.batch_edit.toPlainText())
        return found

    def _validate(self) -> None:
        urls = self.urls()
        if self.tabs.currentIndex() == 1:
            _, rejected = parse_url_list(self.batch_edit.toPlainText())
            message = self.tr("{0} link(s)").format(len(urls))
            if rejected:
                message += self.tr(", {0} line(s) ignored").format(len(rejected))
            self.batch_status.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(urls))
