"""Segment map: one bar for the whole file; each connection's range fills as it arrives."""

from collections.abc import Sequence

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

Segment = tuple[int, int | None, int]  # start, end, received


class SegmentMap(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._total: int | None = None
        self._segments: tuple[Segment, ...] = ()
        self._complete = False
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(self.tr("Segment map"))

    def sizeHint(self) -> QSize:
        return QSize(400, 32)

    def set_data(self, total: int | None, segments: Sequence[Segment]) -> None:
        self._total = total
        self._segments = tuple(segments)
        self.update()

    def set_complete(self, complete: bool) -> None:
        self._complete = complete
        self.update()

    def filled_fraction(self) -> float:
        """Share of the file received (what the bar shows)."""
        if self._complete:
            return 1.0
        if not self._total:
            return 0.0
        return min(sum(r for _, _, r in self._segments) / self._total, 1.0)

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        bar = QRectF(self.rect()).adjusted(1, 4, -1, -4)
        p.setPen(QPen(pal.mid().color(), 1))
        p.setBrush(pal.base())
        p.drawRoundedRect(bar, 4, 4)
        fill = pal.highlight().color()
        if self._complete:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(bar, 4, 4)
            return
        if not self._total:
            p.setPen(pal.placeholderText().color())
            p.drawText(bar, Qt.AlignmentFlag.AlignCenter, self.tr("size unknown"))
            return
        scale = bar.width() / self._total
        dim = QColor(fill)
        dim.setAlpha(60)
        for start, end, received in self._segments:
            if end is None:
                continue
            x0 = bar.left() + start * scale
            span = QRectF(x0, bar.top(), max((end - start) * scale, 1), bar.height())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dim)
            p.drawRect(span)
            p.setBrush(fill)
            p.drawRect(QRectF(x0, bar.top(), received * scale, bar.height()))
            p.setPen(QPen(pal.window().color(), 1))
            p.drawLine(span.topLeft(), span.bottomLeft())  # boundary between connections
