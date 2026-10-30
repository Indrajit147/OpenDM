"""Live speed graph of the last 60 samples (one per second)."""

from collections import deque

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from opendm.core.units import format_bytes

SAMPLES = 60


class SpeedGraph(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.samples: deque[float] = deque(maxlen=SAMPLES)
        self.setMinimumHeight(90)
        self.setAccessibleName(self.tr("Speed graph"))

    def sizeHint(self) -> QSize:
        return QSize(400, 110)

    def add_sample(self, bytes_per_second: float) -> None:
        self.samples.append(max(bytes_per_second, 0.0))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        area = QRectF(self.rect()).adjusted(1, 16, -1, -1)
        p.fillRect(self.rect(), pal.base())
        p.setPen(QPen(pal.mid().color(), 1))
        p.drawRect(area)
        peak = max(self.samples, default=0.0)
        p.setPen(pal.text().color())
        p.drawText(QRectF(4, 0, area.width(), 16), Qt.AlignmentFlag.AlignLeft,
                   self.tr("peak {0}/s").format(format_bytes(peak)))  # fmt: skip
        if len(self.samples) < 2 or peak <= 0:
            return
        step = area.width() / (SAMPLES - 1)
        offset = SAMPLES - len(self.samples)
        points = [
            QPointF(area.left() + (offset + i) * step, area.bottom() - v / peak * area.height())
            for i, v in enumerate(self.samples)
        ]
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        fill = QPainterPath(line)
        fill.lineTo(points[-1].x(), area.bottom())
        fill.lineTo(points[0].x(), area.bottom())
        fill.closeSubpath()
        color = pal.highlight().color()
        shade = QColor(color)
        shade.setAlpha(70)
        p.fillPath(fill, shade)
        p.setPen(QPen(color, 2))
        p.drawPath(line)
