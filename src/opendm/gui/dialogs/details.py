"""Download details: live speed graph, connection count and segment map."""

import time

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opendm.core.events import Progress
from opendm.core.models import Job, JobState
from opendm.core.redact import redact_url
from opendm.core.units import format_bytes, format_duration
from opendm.gui.engine_client import EngineClient
from opendm.gui.models.downloads import status_text
from opendm.gui.widgets.segment_map import SegmentMap
from opendm.gui.widgets.speed_graph import SpeedGraph

_RUNNING = {JobState.PROBING, JobState.DOWNLOADING, JobState.VERIFYING}


class DetailsDialog(QDialog):
    def __init__(self, client: EngineClient, job: Job, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(job.name)
        self.resize(560, 360)
        self._client = client
        self.job = job
        self._last_sample = 0.0
        self.name_label = QLabel(job.name)
        self.url_label = QLabel(redact_url(job.request.url))
        self.url_label.setWordWrap(True)
        self.status_label = QLabel()
        self.progress_label = QLabel()
        self.speed_label = QLabel()
        self.connections_label = QLabel("0")
        form = QFormLayout()
        form.addRow(self.tr("File:"), self.name_label)
        form.addRow(self.tr("Link:"), self.url_label)
        form.addRow(self.tr("Status:"), self.status_label)
        form.addRow(self.tr("Downloaded:"), self.progress_label)
        form.addRow(self.tr("Speed:"), self.speed_label)
        form.addRow(self.tr("Connections:"), self.connections_label)
        self.graph = SpeedGraph()
        self.segment_map = SegmentMap()
        self.toggle_button = QPushButton()
        self.toggle_button.clicked.connect(self._toggle)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(self.toggle_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel(self.tr("Speed (last minute):")))
        layout.addWidget(self.graph)
        layout.addWidget(QLabel(self.tr("Connections and progress:")))
        layout.addWidget(self.segment_map)
        layout.addWidget(buttons)
        client.progress.connect(self._on_progress)
        client.jobUpdated.connect(self._on_job)
        self._show_job()

    def _on_job(self, job: Job) -> None:
        if job.id == self.job.id:
            self.job = job
            self._show_job()

    def _show_job(self) -> None:
        job = self.job
        self.name_label.setText(job.name)
        self.status_label.setText(status_text(job))
        size = format_bytes(job.size) if job.size is not None else "?"
        self.progress_label.setText(f"{format_bytes(job.downloaded)} / {size}")
        running = job.state in _RUNNING
        self.toggle_button.setText(self.tr("Pause") if running else self.tr("Resume"))
        self.toggle_button.setEnabled(job.state is not JobState.COMPLETED)
        self.segment_map.set_complete(job.state is JobState.COMPLETED)
        if not running:
            self.speed_label.setText("")
            self.connections_label.setText("0")

    def _on_progress(self, event: Progress) -> None:
        if event.job_id != self.job.id:
            return
        size = format_bytes(event.total) if event.total is not None else "?"
        self.progress_label.setText(f"{format_bytes(event.downloaded)} / {size}")
        eta = format_duration(event.eta) if event.eta is not None else "--:--"
        self.speed_label.setText(f"{format_bytes(event.speed)}/s, {eta} left")
        self.connections_label.setText(str(event.connections))
        self.segment_map.set_data(event.total, event.segments)
        now = time.monotonic()
        if now - self._last_sample >= 1.0:
            self._last_sample = now
            self.graph.add_sample(event.speed)

    def _toggle(self) -> None:
        job_id = self.job.id
        if self.job.state in _RUNNING:
            self._client.call(lambda m: m.pause(job_id))
        else:
            self._client.call(lambda m: m.start(job_id))

    def closeEvent(self, event) -> None:
        self._client.progress.disconnect(self._on_progress)
        self._client.jobUpdated.disconnect(self._on_job)
        super().closeEvent(event)
