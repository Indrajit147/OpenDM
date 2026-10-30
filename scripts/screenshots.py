r"""Render GUI screenshots with live test-server downloads into build\screens (dev aid).

Nothing is shown on screen: windows are rendered with grab(). Run from the repo root:
    .venv\Scripts\python.exe scripts\screenshots.py
"""

import dataclasses
import os
import sys
import time
from pathlib import Path

os.environ["OPENDM_IPC_NAME"] = "opendm-screens"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from opendm.gui.app import Application
from opendm.gui.theme import apply_theme
from tests.server.app import FaultServer

out = Path(__file__).resolve().parents[1] / "build" / "screens"
out.mkdir(parents=True, exist_ok=True)
work = out / "work"
qapp = QApplication([])
server = FaultServer().start()
app = Application(
    qapp, work / "data", downloads=work / "dl", ipc_name="opendm-screens", power=lambda a: None
)
app.save_settings(dataclasses.replace(app.settings, first_run_done=True, per_host=32))
# Never show anything on the user's screen: windows are rendered off-screen with grab().
app.window.show = lambda: None  # type: ignore[method-assign]
app.window.showNormal = lambda: None  # type: ignore[method-assign]
app.start(wizard=False)
from opendm.gui.dialogs.details import DetailsDialog  # noqa: E402
from opendm.gui.dialogs.start_download import StartDownloadDialog  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)


spin(0.5)
urls = [
    server.url("/file/ubuntu-24.04-desktop-amd64.iso?size=40M&rate=1M"),
    server.url("/file/holiday-video.mp4?size=20M&rate=512K"),
    server.url("/file/annual-report.pdf?size=300K"),
    server.url("/file/music-album.zip?size=30M&rate=256K"),
    server.url("/status/404"),
]
app.window.add_urls(urls, ask=False)
spin(4)
app.window.resize(1000, 600)
app.window.grab().save(str(out / "main-light.png"))
job = next(j for j in app.window.model.jobs() if j.name.startswith("music"))
details = DetailsDialog(app.client, job)
details.resize(560, 380)
spin(4.5)
details.grab().save(str(out / "details-light.png"))
apply_theme(qapp, "dark")
spin(1)
app.window.grab().save(str(out / "main-dark.png"))
from opendm.core.models import DownloadRequest  # noqa: E402

dialog = StartDownloadDialog(
    app.client,
    DownloadRequest(server.url("/file/setup-tool.exe?size=5M"), work / "dl"),
    base_dir=work / "dl",
    categories=app.window.categories,
    queues=app.window.queues,
)
dialog.resize(600, 320)
spin(1.5)
dialog.grab().save(str(out / "start-dialog-dark.png"))
app.shutdown()
server.stop()
print("saved to", out)
