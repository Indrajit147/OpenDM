r"""Write the extension icons (extension\icons\icon{16,32,48,128}.png) from the app icon.

Run from the repo root after changing gui\icons.py:
    .venv\Scripts\python.exe scripts\make_extension_icons.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtGui import QGuiApplication

from opendm.gui.icons import _render

app = QGuiApplication([])
out = Path(__file__).resolve().parents[1] / "extension" / "icons"
out.mkdir(parents=True, exist_ok=True)
for size in (16, 32, 48, 128):
    if not _render(size).save(str(out / f"icon{size}.png"), "PNG"):
        raise SystemExit(f"could not write icon{size}.png")
print(f"icons written to {out}")
