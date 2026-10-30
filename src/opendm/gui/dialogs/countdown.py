"""60-second cancellable countdown before sleep or shutdown (spec 6.3)."""

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from opendm.core.models import AfterAction


class CountdownDialog(QDialog):
    def __init__(
        self,
        action: AfterAction,
        queue_name: str,
        execute: Callable[[AfterAction], None],
        *,
        seconds: int = 60,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.action = action
        self._execute = execute
        self.remaining = seconds
        self.executed = False
        verb = self.tr("shut down") if action is AfterAction.SHUTDOWN else self.tr("go to sleep")
        self.setWindowTitle(self.tr("Queue finished"))
        self._verb = verb
        self._queue = queue_name
        self.label = QLabel()
        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.now_button = buttons.addButton(
            self.tr("Do it now"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.rejected.connect(self.reject)
        self.now_button.clicked.connect(self._fire)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._render()

    def _render(self) -> None:
        self.label.setText(
            self.tr('Queue "{0}" has finished. The computer will {1} in {2} seconds.').format(
                self._queue, self._verb, self.remaining
            )
        )

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self._fire()
        else:
            self._render()

    def _fire(self) -> None:
        self._timer.stop()
        if not self.executed:
            self.executed = True
            self.accept()
            self._execute(self.action)

    def reject(self) -> None:
        self._timer.stop()
        super().reject()
