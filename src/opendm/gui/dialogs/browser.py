"""Settings -> Browser: connect OpenDM to Chrome and Edge (Native Messaging host + extension)."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class BrowserPanel(QWidget):
    def __init__(
        self,
        *,
        status: Callable[[], dict[str, Path | None]],
        register: Callable[[], Path],
        unregister: Callable[[], None],
        extension_dir: Path,
        open_folder: Callable[[Path], object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._status, self._register, self._unregister = status, register, unregister
        self._extension_dir, self._open_folder = extension_dir, open_folder
        layout = QVBoxLayout(self)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        self.setup_button = QPushButton(self.tr("Set up for Chrome and Edge"))
        self.remove_button = QPushButton(self.tr("Remove"))
        self.setup_button.clicked.connect(lambda: self._run(self._register))
        self.remove_button.clicked.connect(lambda: self._run(self._unregister))
        row.addWidget(self.setup_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.instructions = QLabel(self.tr(
            "Then add the OpenDM Integration extension: open chrome://extensions (or "
            "edge://extensions), turn on Developer mode, click Load unpacked and choose\n{0}"
        ).format(extension_dir))  # fmt: skip
        self.instructions.setWordWrap(True)
        self.instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.instructions)
        self.folder_button = QPushButton(self.tr("Open extension folder"))
        self.folder_button.clicked.connect(lambda: self._open_folder(self._extension_dir))
        self.folder_button.setEnabled(extension_dir.is_dir())
        layout.addWidget(self.folder_button)
        layout.addStretch()
        self.refresh()

    def _run(self, action: Callable[[], object]) -> None:
        try:
            action()
        except OSError as exc:
            self.message.setText(self.tr("Could not change the browser setup: {0}").format(exc))
        else:
            self.message.clear()
        self.refresh()

    def refresh(self) -> None:
        states = self._status()
        lines = [
            f"{browser}: " + (self.tr("set up") if manifest else self.tr("not set up"))
            for browser, manifest in states.items()
        ]
        self.status_label.setText("\n".join(lines))
        any_set = any(states.values())
        self.remove_button.setEnabled(any_set)
        self.setup_button.setText(
            self.tr("Repair") if all(states.values()) else self.tr("Set up for Chrome and Edge")
        )
