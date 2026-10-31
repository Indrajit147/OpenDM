r"""Images for the Chrome Web Store and Edge Add-ons listings, written to store\images.

    .venv\Scripts\python.exe scripts\screenshots.py      (renders build\screens first)
    .venv\Scripts\python.exe scripts\store_assets.py

promo-440x280.png (small promo tile), icon-300.png (Edge logo), icon-128.png and
screenshot-*-1280x800.png (the app's own screens, letterboxed). Everything is drawn from
OpenDM's own icon and screenshots.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from opendm.gui.icons import _render  # noqa: E402

OUT = ROOT / "store" / "images"
SCREENS = ROOT / "build" / "screens"
DARK = QColor("#1b1d21")
TEAL = QColor("#2f9e8f")


def promo(path: Path) -> None:
    image = QImage(440, 280, QImage.Format.Format_ARGB32)
    image.fill(DARK)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(40, 76, _render(128))
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
    painter.drawText(QRect(190, 80, 240, 60), Qt.AlignmentFlag.AlignLeft, "OpenDM")
    painter.setPen(TEAL)
    painter.setFont(QFont("Segoe UI", 13))
    painter.drawText(QRect(190, 140, 240, 80), Qt.TextFlag.TextWordWrap,
                     "Free, open-source download manager for Windows")  # fmt: skip
    painter.end()
    image.save(str(path))


def letterbox(source: Path, path: Path, caption: str) -> None:
    shot = QImage(str(source))
    canvas = QImage(1280, 800, QImage.Format.Format_ARGB32)
    canvas.fill(DARK)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 22, QFont.Weight.DemiBold))
    painter.drawText(QRect(0, 24, 1280, 50), Qt.AlignmentFlag.AlignCenter, caption)
    area = QRect(40, 96, 1200, 680)
    scaled = shot.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)  # fmt: skip
    x = area.x() + (area.width() - scaled.width()) // 2
    y = area.y() + (area.height() - scaled.height()) // 2
    painter.drawImage(x, y, scaled)
    painter.end()
    canvas.save(str(path))


def main() -> int:
    if not (SCREENS / "main-dark.png").is_file():
        print("run scripts\\screenshots.py first")
        return 2
    QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    _render(128).save(str(OUT / "icon-128.png"))
    _render(300).save(str(OUT / "icon-300.png"))  # Edge Add-ons store logo
    promo(OUT / "promo-440x280.png")
    for name, caption in (
        ("main-dark", "Downloads from Chrome and Edge go straight to OpenDM"),
        ("media-dialog-dark", "Pick the quality for videos, or save just the audio"),
        ("details-light", "Fast multi-connection downloads that resume after a break"),
    ):
        letterbox(SCREENS / f"{name}.png", OUT / f"screenshot-{name}-1280x800.png", caption)
    print("saved to", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
