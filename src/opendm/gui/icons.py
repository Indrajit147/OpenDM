"""The app icon, drawn in code (original artwork, GPL like the rest of OpenDM)."""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


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


def _png(size: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    _render(size).save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def write_ico(path: Path) -> Path:
    """Write a Windows .ico with PNG images (Vista+ format) for the exes and the installer."""
    images = [_png(size) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, image in zip(ICO_SIZES, images, strict=True):
        side = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(images))
    return path
