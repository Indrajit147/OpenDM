"""Queues dialog: concurrency, schedule, days and after-queue action."""

import dataclasses

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from opendm.core.models import MAIN_QUEUE_ID, AfterAction, Queue
from opendm.gui.engine_client import EngineClient

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class QueuesDialog(QDialog):
    def __init__(self, client: EngineClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Queues"))
        self.resize(640, 380)
        self._client = client
        self._queues: list[Queue] = []
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._show)

        self.name = QLineEdit()
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 32)
        self.scheduled = QCheckBox(self.tr("Start at"))
        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm")
        self.has_stop = QCheckBox(self.tr("Stop at"))
        self.stop_time = QTimeEdit()
        self.stop_time.setDisplayFormat("HH:mm")
        self.days = [QCheckBox(self.tr(day)) for day in DAY_NAMES]
        days_row = QHBoxLayout()
        for box in self.days:
            days_row.addWidget(box)
        self.after = QComboBox()
        for action, label in ((AfterAction.NONE, self.tr("Do nothing")),
                              (AfterAction.SLEEP, self.tr("Sleep")),
                              (AfterAction.SHUTDOWN, self.tr("Shut down"))):  # fmt: skip
            self.after.addItem(label, str(action))
        start_row = QHBoxLayout()
        start_row.addWidget(self.scheduled)
        start_row.addWidget(self.start_time)
        start_row.addWidget(self.has_stop)
        start_row.addWidget(self.stop_time)
        form = QFormLayout()
        form.addRow(self.tr("Name:"), self.name)
        form.addRow(self.tr("Downloads at once:"), self.max_concurrent)
        form.addRow(self.tr("Schedule:"), start_row)
        form.addRow(self.tr("Days:"), days_row)
        form.addRow(self.tr("When finished:"), self.after)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        form.addRow(self.error)

        self.add_button = QPushButton(self.tr("New queue"))
        self.delete_button = QPushButton(self.tr("Delete"))
        self.save_button = QPushButton(self.tr("Save"))
        self.start_button = QPushButton(self.tr("Start queue"))
        self.stop_button = QPushButton(self.tr("Stop queue"))
        self.add_button.clicked.connect(self._add)
        self.delete_button.clicked.connect(self._delete)
        self.save_button.clicked.connect(self.save_current)
        self.start_button.clicked.connect(lambda: self._run(start=True))
        self.stop_button.clicked.connect(lambda: self._run(start=False))
        left = QVBoxLayout()
        left.addWidget(self.list)
        left.addWidget(self.add_button)
        left.addWidget(self.delete_button)
        right = QVBoxLayout()
        right.addLayout(form)
        actions = QHBoxLayout()
        for b in (self.save_button, self.start_button, self.stop_button):
            actions.addWidget(b)
        right.addLayout(actions)
        right.addStretch()
        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(right, 2)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        outer = QVBoxLayout(self)
        outer.addLayout(body)
        outer.addWidget(close)
        self.reload()

    def reload(self, select: int | None = None) -> None:
        self._client.call(lambda m: m.queues.list(), on_done=lambda q: self._loaded(q, select))

    def _loaded(self, queues: list[Queue], select: int | None) -> None:
        self._queues = queues
        self.list.clear()
        for queue in queues:
            item = QListWidgetItem(queue.name)
            self.list.addItem(item)
        row = next((i for i, q in enumerate(queues) if q.id == select), 0)
        self.list.setCurrentRow(row)

    def current(self) -> Queue | None:
        row = self.list.currentRow()
        return self._queues[row] if 0 <= row < len(self._queues) else None

    def _show(self, row: int) -> None:
        queue = self.current()
        if queue is None:
            return
        self.error.clear()
        self.name.setText(queue.name)
        self.max_concurrent.setValue(queue.max_concurrent)
        self.scheduled.setChecked(queue.start_time is not None)
        self.start_time.setTime(QTime.fromString(queue.start_time or "01:00", "HH:mm"))
        self.has_stop.setChecked(queue.stop_time is not None)
        self.stop_time.setTime(QTime.fromString(queue.stop_time or "06:00", "HH:mm"))
        for i, box in enumerate(self.days):
            box.setChecked(bool(queue.days >> i & 1))
        self.after.setCurrentIndex(self.after.findData(str(queue.after_action)))
        self.delete_button.setEnabled(queue.id != MAIN_QUEUE_ID)

    def edited(self) -> Queue | None:
        queue = self.current()
        if queue is None:
            return None
        days = sum(1 << i for i, box in enumerate(self.days) if box.isChecked())
        return dataclasses.replace(
            queue,
            name=self.name.text().strip() or queue.name,
            max_concurrent=self.max_concurrent.value(),
            start_time=self._time(self.scheduled, self.start_time),
            stop_time=self._time(self.has_stop, self.stop_time),
            days=days,
            after_action=AfterAction(self.after.currentData()),
        )  # fmt: skip

    @staticmethod
    def _time(enabled: QCheckBox, edit: QTimeEdit) -> str | None:
        return edit.time().toString("HH:mm") if enabled.isChecked() else None

    def save_current(self) -> None:
        queue = self.edited()
        if queue is None:
            return
        self._client.call(
            lambda m: m.queues.save(queue),
            on_done=lambda _: self.reload(queue.id),
            on_error=lambda e: self.error.setText(str(e)),
        )

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, self.tr("New queue"), self.tr("Name:"))
        if ok and name.strip():
            self._client.call(
                lambda m: m.queues.add(Queue(name.strip())),
                on_done=lambda q: self.reload(q.id),
                on_error=lambda e: self.error.setText(str(e)),
            )

    def _delete(self) -> None:
        queue = self.current()
        if queue is None or queue.id == MAIN_QUEUE_ID:
            return
        answer = QMessageBox.question(
            self, self.tr("Delete queue"),
            self.tr("Delete queue \"{0}\"? Its downloads move to Main.").format(queue.name),
        )  # fmt: skip
        if answer == QMessageBox.StandardButton.Yes:
            self._client.call(lambda m: m.queues.delete(queue.id), on_done=lambda _: self.reload())

    def _run(self, start: bool) -> None:
        queue = self.current()
        if queue is None or queue.id is None:
            return
        queue_id = queue.id
        if start:
            self._client.call(lambda m: m.start_queue(queue_id))
        else:
            self._client.call(lambda m: m.stop_queue(queue_id))
