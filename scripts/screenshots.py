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
    server.url("/file/fonts-collection.zip?size=2M"),
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

# M5 dialogs. The quality picker uses a real analysis when OPENDM_TEST_TOOLS points at
# yt-dlp/FFmpeg and the media fixtures exist; otherwise a sample description.
from opendm.engine.media.ytdlp import MediaEntry, MediaInfo, ToolPaths  # noqa: E402
from opendm.gui.dialogs.media import MediaDialog  # noqa: E402
from opendm.gui.dialogs.tools import ToolsConsentDialog  # noqa: E402

info = MediaInfo(
    url="https://example.com/watch", title="Sample video (test pattern)", duration=5,
    uploader="OpenDM tests", heights=[1080, 720, 480], subtitles=["en"], auto_subtitles=["bn"],
)  # fmt: skip
tools_dir = os.environ.get("OPENDM_TEST_TOOLS")
fixtures = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media"
if tools_dir and (fixtures / "page.html").exists():
    base = Path(tools_dir)
    paths = ToolPaths(ytdlp=base / "yt-dlp" / "yt-dlp.exe",
                      ffmpeg=base / "ffmpeg" / "bin" / "ffmpeg.exe")  # fmt: skip
    server.static_root = fixtures
    app.engine.call(lambda m: m.set_tools(paths)).result(5)
    request = DownloadRequest(server.url("/static/page.html"), work / "dl")
    info = app.engine.call(lambda m: m.analyze_media(request)).result(120)
picker = MediaDialog(info, base_dir=work / "dl", categories=app.window.categories,
                     queues=app.window.queues)  # fmt: skip
picker.resize(560, 360)
spin(0.5)
picker.grab().save(str(out / "media-dialog-dark.png"))
playlist = MediaInfo(
    url="https://example.com/list", title="Sample playlist", uploader="OpenDM tests",
    entries=[MediaEntry(f"https://example.com/v/{i}", f"Episode {i}", 600 + i * 30)
             for i in range(1, 6)],
)  # fmt: skip
list_picker = MediaDialog(playlist, base_dir=work / "dl", categories=app.window.categories,
                          queues=app.window.queues)  # fmt: skip
list_picker.resize(560, 520)
spin(0.5)
list_picker.grab().save(str(out / "playlist-dialog-dark.png"))
consent = ToolsConsentDialog(["yt-dlp", "ffmpeg"], Path(r"D:\Apps\OpenDM\tools"),
                             {"yt-dlp": 23_592_960, "ffmpeg": 114_819_072})  # fmt: skip
consent.resize(520, 330)
spin(0.5)
consent.grab().save(str(out / "consent-dialog-dark.png"))
app.shutdown()
server.stop()
print("saved to", out)
