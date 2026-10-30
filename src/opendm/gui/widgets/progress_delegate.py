"""Draws the progress column as a progress bar."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyleOptionViewItem,
)

from opendm.gui.models.downloads import JOB_ROLE, LIVE_STATES, PROGRESS_ROLE


class ProgressDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        fraction = index.data(PROGRESS_ROLE)
        if fraction is None:
            super().paint(painter, option, index)
            return
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(3, 3, -3, -3)
        bar.minimum, bar.maximum = 0, 1000
        if fraction < 0:
            job = index.data(JOB_ROLE)
            if job is None or job.state not in LIVE_STATES:
                return  # unknown size and not running (failed, paused): no bar at all
            bar.maximum = 0  # busy indicator: running, size unknown
            bar.progress = 0
            bar.text = ""
        else:
            bar.progress = int(fraction * 1000)
            bar.text = f"{fraction * 100:.1f}%"
        bar.textVisible = True
        bar.textAlignment = Qt.AlignmentFlag.AlignCenter
        bar.state = option.state | QStyle.StateFlag.State_Enabled
        bar.palette = option.palette
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter, option.widget)
