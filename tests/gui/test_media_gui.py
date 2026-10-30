"""GUI media flow (M5): consent, analysis, quality picker, DRM message, Tools panel."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from opendm.core.models import DownloadRequest, JobState
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import ToolPaths
from opendm.gui import app as app_module
from opendm.ipc import client
from opendm.tools.manager import ToolManager
from opendm.tools.sources import Sources
from tests.gui.conftest import GuiApp
from tests.gui.test_ipc import in_thread
from tests.server.app import FaultServer

FAKE = Path(__file__).resolve().parents[1] / "fake_tools" / "fake_ytdlp.py"
WAIT = 20_000


async def fake_probe(path: Path) -> str | None:
    if not path.is_file():
        return None
    data = path.read_bytes()
    return "fake 1.0" if data.startswith((b"FAKE", b"FFMPEG", b"FFPROBE")) else None


def use_fake_tools(gui: GuiApp, tmp_path: Path, sources: Sources | None = None, *,
                   installed: bool = True) -> None:  # fmt: skip
    overrides = {}
    if installed:
        for name, rel in (("yt-dlp", "yt/yt-dlp.exe"), ("ffmpeg", "ff/ffmpeg.exe")):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"FAKE")
            overrides[name] = path
    ffmpeg = overrides.get("ffmpeg")

    def setup(m) -> None:
        m.tool_manager = ToolManager(tmp_path / "tools", sources=sources, overrides=overrides,
                                     version_probe=fake_probe)  # fmt: skip
        m.set_tools(ToolPaths(ffmpeg=ffmpeg, command=(sys.executable, str(FAKE))))

    gui.engine.call(setup).result(5)


@pytest.fixture
def boxes(monkeypatch) -> list[tuple[str, str]]:
    """Record message boxes instead of blocking on them."""
    shown: list[tuple[str, str]] = []

    def information(parent, title, text, *a, **k):
        shown.append(("information", text))
        return QMessageBox.StandardButton.Ok

    def question(parent, title, text, *a, **k):
        shown.append(("question", text))
        return QMessageBox.StandardButton.No

    def warning(parent, title, text, *a, **k):
        shown.append(("warning", text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(app_module.QMessageBox, "information", information)
    monkeypatch.setattr(app_module.QMessageBox, "question", question)
    monkeypatch.setattr(app_module.QMessageBox, "warning", warning)
    return shown


def test_video_page_to_completed_download(qtbot, gui: GuiApp, tmp_path: Path) -> None:
    use_fake_tools(gui, tmp_path)
    gui.open_media(DownloadRequest("http://fake/ok", gui.settings.download_dir))
    qtbot.waitUntil(lambda: gui.media_dialog is not None and gui.media_dialog.isVisible(),
                    timeout=WAIT)  # fmt: skip
    dialog = gui.media_dialog
    assert dialog is not None
    qualities = [dialog.quality.itemData(i) for i in range(dialog.quality.count())]
    assert qualities == ["best", "1080", "720", "audio-mp3", "audio-m4a"]
    subs = [dialog.subtitles.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(dialog.subtitles.count())]  # fmt: skip
    assert subs == ["en", "auto:bn"]
    assert Path(dialog.folder_edit.text()) == tmp_path / "dl" / "Video"
    dialog.quality.setCurrentIndex(qualities.index("720"))
    dialog.start_button.click()

    def done() -> bool:
        jobs = gui.window.model.jobs()
        return bool(jobs) and jobs[0].state is JobState.COMPLETED

    qtbot.waitUntil(done, timeout=WAIT)
    job = gui.window.model.jobs()[0]
    assert job.kind == "media" and job.media_options["quality"] == "720"  # type: ignore[index]
    assert job.final_path == tmp_path / "dl" / "Video" / "Fake Clip [abc].mp4"


def test_audio_choice_goes_to_audio_folder(qtbot, gui: GuiApp, tmp_path: Path) -> None:
    use_fake_tools(gui, tmp_path)
    gui.open_media(DownloadRequest("http://fake/ok", gui.settings.download_dir))
    qtbot.waitUntil(lambda: gui.media_dialog is not None, timeout=WAIT)
    dialog = gui.media_dialog
    assert dialog is not None
    dialog.quality.setCurrentIndex(dialog.quality.findData("audio-mp3"))
    assert not dialog.container.isEnabled()
    assert Path(dialog.folder_edit.text()) == tmp_path / "dl" / "Audio"


def test_playlist_selection(qtbot, gui: GuiApp, tmp_path: Path) -> None:
    use_fake_tools(gui, tmp_path)
    gui.open_media(DownloadRequest("http://fake/playlist", gui.settings.download_dir))
    qtbot.waitUntil(lambda: gui.media_dialog is not None, timeout=WAIT)
    dialog = gui.media_dialog
    assert dialog is not None and dialog.entries.count() == 3
    dialog.entries.item(1).setCheckState(Qt.CheckState.Unchecked)
    dialog.queue_button.click()  # "Add to queue": nothing starts
    qtbot.waitUntil(lambda: len(gui.window.model.jobs()) == 2, timeout=WAIT)
    urls = sorted(j.request.url for j in gui.window.model.jobs())
    assert urls == ["http://fake/ok/1", "http://fake/ok/3"]
    assert all(j.state is JobState.QUEUED for j in gui.window.model.jobs())
    dialog_none = gui.media_dialog
    dialog_none._set_all(Qt.CheckState.Unchecked)  # type: ignore[union-attr]
    assert not dialog_none.start_button.isEnabled()  # type: ignore[union-attr]


def test_protected_content_message(qtbot, gui: GuiApp, tmp_path: Path, boxes) -> None:
    use_fake_tools(gui, tmp_path)
    gui.open_media(DownloadRequest("http://fake/drm", gui.settings.download_dir))
    qtbot.waitUntil(lambda: bool(boxes), timeout=WAIT)
    assert boxes[0][0] == "information" and "not supported" in boxes[0][1]
    assert gui.media_dialog is None


def test_no_media_offers_plain_download(qtbot, gui: GuiApp, tmp_path: Path, boxes) -> None:
    use_fake_tools(gui, tmp_path)
    gui.open_media(DownloadRequest("http://fake/netfail", gui.settings.download_dir))
    qtbot.waitUntil(lambda: bool(boxes), timeout=WAIT)
    assert boxes[0][0] == "question" and "normal file" in boxes[0][1]


@pytest.fixture
def fake_release(server: FaultServer, tmp_path: Path):
    root = tmp_path / "static"
    (root / "rel").mkdir(parents=True)
    (root / "ff").mkdir()
    exe = b"FAKE-YTDLP" * 100
    (root / "rel" / "yt-dlp.exe").write_bytes(exe)
    (root / "rel" / "SHA2-256SUMS").write_text(f"{hashlib.sha256(exe).hexdigest()}  yt-dlp.exe\n")
    (root / "api.json").write_text(json.dumps({"tag_name": "2099.01.01", "assets": [
        {"name": "yt-dlp.exe", "size": len(exe),
         "browser_download_url": server.url("/static/rel/yt-dlp.exe")},
        {"name": "SHA2-256SUMS", "browser_download_url": server.url("/static/rel/SHA2-256SUMS")},
    ]}))  # fmt: skip
    with zipfile.ZipFile(root / "ff" / "ff.zip", "w") as z:
        z.writestr("build/bin/ffmpeg.exe", b"FFMPEG")
        z.writestr("build/bin/ffprobe.exe", b"FFPROBE")
    (root / "ff" / "ff.zip.sha256").write_text(
        hashlib.sha256((root / "ff" / "ff.zip").read_bytes()).hexdigest()
    )
    (root / "ff" / "version").write_text("9.0.2")
    server.static_root = root
    yield Sources(
        ytdlp_api=server.url("/static/api.json"),
        ytdlp_download_prefix=server.url("/static/rel/"),
        ffmpeg_zip=server.url("/static/ff/ff.zip"),
        ffmpeg_sha256=server.url("/static/ff/ff.zip.sha256"),
        ffmpeg_version=server.url("/static/ff/version"),
    )
    server.static_root = None


def test_consent_then_verified_install(
    qtbot, gui: GuiApp, tmp_path: Path, fake_release, boxes
) -> None:
    use_fake_tools(gui, tmp_path, fake_release, installed=False)
    gui.open_media(DownloadRequest("http://fake/ok", gui.settings.download_dir))
    qtbot.waitUntil(lambda: gui.consent_dialog is not None, timeout=WAIT)
    consent = gui.consent_dialog
    assert consent is not None and consent.missing == ["yt-dlp", "ffmpeg"]
    assert consent.folder() == gui.settings.tools_dir
    consent.accept()
    tools = tmp_path / "tools"
    qtbot.waitUntil(lambda: (tools / "ffmpeg" / "bin" / "ffprobe.exe").exists(), timeout=WAIT)
    assert (tools / "yt-dlp" / "yt-dlp.exe").read_bytes().startswith(b"FAKE-YTDLP")
    # After installing, OpenDM goes on to analyze the page (the fake "exe" cannot run, so it
    # then offers a plain download - that is the expected follow-up here).
    qtbot.waitUntil(lambda: bool(boxes), timeout=WAIT)


def test_declining_consent_downloads_nothing(
    qtbot, gui: GuiApp, tmp_path: Path, fake_release
) -> None:
    use_fake_tools(gui, tmp_path, fake_release, installed=False)
    gui.open_media(DownloadRequest("http://fake/ok", gui.settings.download_dir))
    qtbot.waitUntil(lambda: gui.consent_dialog is not None, timeout=WAIT)
    gui.consent_dialog.reject()  # type: ignore[union-attr]
    qtbot.wait(500)
    assert not (tmp_path / "tools").exists()


def test_start_dialog_hands_pages_to_media_flow(qtbot, gui: GuiApp, server: FaultServer,
                                                tmp_path: Path) -> None:  # fmt: skip
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "watch.html").write_text("<html><video src='v.mp4'></video></html>")
    server.static_root = tmp_path / "web"
    seen: list[DownloadRequest] = []
    gui.window.mediaRequested.disconnect()
    gui.window.mediaRequested.connect(seen.append)
    try:
        dialog = gui.window.add_urls([server.url("/static/watch.html")])
        qtbot.waitUntil(lambda: bool(seen), timeout=WAIT)
        assert seen[0].url.endswith("/static/watch.html")
        assert dialog is not None and not dialog.isVisible()
    finally:
        server.static_root = None


def test_settings_tools_panel(qtbot, gui: GuiApp, tmp_path: Path, fake_release) -> None:
    use_fake_tools(gui, tmp_path, fake_release)
    settings = gui.open_settings()
    panel = gui.tools_panel
    assert panel is not None
    qtbot.waitUntil(lambda: "fake 1.0" in panel.labels["yt-dlp"].text(), timeout=WAIT)
    panel.check_update()
    qtbot.waitUntil(lambda: "2099.01.01" in panel.update_label.text(), timeout=WAIT)
    panel.update_check.setChecked(True)
    settings.accept()
    assert gui.settings.tool_update_check


def test_ipc_media_add(qtbot, gui: GuiApp, tmp_path: Path) -> None:
    use_fake_tools(gui, tmp_path)
    args = {"url": "http://fake/ok", "media": {"quality": "audio-m4a"}, "start": False}
    added = in_thread(qtbot, lambda: client.request("add", args))
    qtbot.waitUntil(lambda: bool(gui.window.model.jobs()), timeout=WAIT)
    job = gui.window.model.job(added["id"])
    assert job is not None and job.kind == "media"
    assert job.request.dest_dir == tmp_path / "dl" / "Audio"


def test_missing_tools_are_offered_once(qtbot, gui: GuiApp, tmp_path: Path, fake_release) -> None:
    use_fake_tools(gui, tmp_path, fake_release, installed=False)  # yt-dlp stand-in, no FFmpeg
    jobs = [
        gui.client.call(
            lambda m, n=n: m.add_media(
                DownloadRequest(f"http://fake/ok/{n}", tmp_path / "dl"),
                MediaOptions(quality="audio-mp3"),
            )
        ).result(5)
        for n in range(3)
    ]
    qtbot.waitUntil(lambda: gui.consent_dialog is not None, timeout=WAIT)
    first = gui.consent_dialog
    assert first is not None and first.missing == ["ffmpeg"]
    qtbot.wait(300)
    assert gui.consent_dialog is first  # one question, not one per download
    stored = [gui.client.call(lambda m, j=j: m.jobs.get(j.id)).result(5) for j in jobs]
    assert all(j.state is JobState.QUEUED and "FFmpeg" in j.message for j in stored)
    first.reject()


def test_video_in_a_playlist_offers_the_whole_list(qtbot, gui: GuiApp, tmp_path: Path) -> None:
    use_fake_tools(gui, tmp_path)
    url = "http://fake/playlist?v=abc&list=RD1"
    gui.open_media(DownloadRequest(url, gui.settings.download_dir))
    qtbot.waitUntil(lambda: gui.media_dialog is not None, timeout=WAIT)
    single = gui.media_dialog
    assert single is not None and not single.info.is_playlist
    assert single.playlist_button.isVisible()
    single.playlist_button.click()
    qtbot.waitUntil(lambda: gui.media_dialog is not single, timeout=WAIT)
    whole = gui.media_dialog
    assert whole is not None and whole.info.is_playlist and whole.entries.count() == 3
    assert not single.isVisible() and not whole.playlist_button.isVisible()
