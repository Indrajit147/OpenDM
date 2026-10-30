"""The app icon, drawn in code (original artwork, GPL like the rest of OpenDM)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _render(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    gradient = QLinearGradient(0, 0, 0, s)
    gradient.setColorAt(0, QColor("#2f9e8f"))
    gradient.setColorAt(1, QColor("#1d6f86"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.22, s * 0.22)
    # Arrow into a tray: "open download".
    white = QColor("#ffffff")
    pen = QPen(white, max(1.5, s * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.5, s * 0.2), QPointF(s * 0.5, s * 0.58))
    head = QPainterPath(QPointF(s * 0.32, s * 0.42))
    head.lineTo(s * 0.5, s * 0.6)
    head.lineTo(s * 0.68, s * 0.42)
    p.drawPath(head)
    tray = QPainterPath(QPointF(s * 0.24, s * 0.62))
    tray.lineTo(s * 0.24, s * 0.76)
    tray.lineTo(s * 0.76, s * 0.76)
    tray.lineTo(s * 0.76, s * 0.62)
    p.drawPath(tray)
    p.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(_render(size))
    return icon
