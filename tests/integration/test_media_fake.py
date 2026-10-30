"""Media engine against the fake yt-dlp (no real tools needed)."""

import asyncio
import ctypes
import hashlib
import json
import sys
from pathlib import Path

import pytest

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.events import Event, Failed, Progress, StateChanged
from opendm.core.models import DownloadRequest, JobState
from opendm.core.settings import EngineSettings
from opendm.engine.media.download import MediaDownload
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import ToolPaths, analyze

FAKE = Path(__file__).resolve().parents[1] / "fake_tools" / "fake_ytdlp.py"


@pytest.fixture
def tools(tmp_path: Path, monkeypatch) -> ToolPaths:
    ffmpeg = tmp_path / "tools" / "ffmpeg.exe"
    ffmpeg.parent.mkdir()
    ffmpeg.write_bytes(b"")  # only its presence is checked
    monkeypatch.setenv("FAKE_YTDLP_LOG", str(tmp_path / "calls.jsonl"))
    return ToolPaths(ffmpeg=ffmpeg, command=(sys.executable, str(FAKE)))


def calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def make(
    tools: ToolPaths, tmp_path: Path, url: str, options: MediaOptions | None = None, **kwargs
) -> tuple[MediaDownload, list[Event]]:
    events: list[Event] = []
    request = DownloadRequest(url=url, dest_dir=tmp_path / "dl", **kwargs)
    download = MediaDownload(
        request, options or MediaOptions(), tools=tools, temp_dir=tmp_path / "tmp",
        settings=EngineSettings(progress_interval=0.0), sink=events.append,
    )  # fmt: skip
    return download, events


# --- analysis ----------------------------------------------------------------------------------


async def test_analyze_video(tools: ToolPaths, tmp_path: Path) -> None:
    info = await analyze(tools, DownloadRequest("http://fake/ok", tmp_path), temp_dir=tmp_path)
    assert (info.title, info.id, info.duration) == ("Fake Clip", "abc", 5)
    assert info.heights == [1080, 720]
    assert info.subtitles == ["en"] and info.auto_subtitles == ["bn"]
    assert not info.is_playlist


async def test_analyze_playlist(tools: ToolPaths, tmp_path: Path) -> None:
    info = await analyze(
        tools, DownloadRequest("http://fake/playlist", tmp_path), temp_dir=tmp_path
    )
    assert info.is_playlist and info.title == "Fake List"
    assert [e.title for e in info.entries] == ["Item 1", "Item 2", "Item 3"]
    assert info.entries[0].url == "http://fake/ok/1"


@pytest.mark.parametrize(
    ("url", "kind"),
    [("http://fake/drm", ErrorKind.PROTECTED), ("http://fake/netfail", ErrorKind.NETWORK)],
)
async def test_analyze_errors(tools: ToolPaths, tmp_path: Path, url: str, kind) -> None:
    with pytest.raises(DownloadError) as exc:
        await analyze(tools, DownloadRequest(url, tmp_path), temp_dir=tmp_path)
    assert exc.value.kind is kind
    if kind is ErrorKind.PROTECTED:
        assert "not supported" in exc.value.message


async def test_missing_tool(tmp_path: Path) -> None:
    with pytest.raises(DownloadError) as exc:
        await analyze(ToolPaths(), DownloadRequest("http://fake/ok", tmp_path), temp_dir=tmp_path)
    assert exc.value.kind is ErrorKind.TOOL_MISSING


# --- downloads ---------------------------------------------------------------------------------


async def test_download_and_arguments(tools: ToolPaths, tmp_path: Path) -> None:
    download, events = make(
        tools, tmp_path, "http://fake/ok", cookies="s=SECRET",
        headers={"Authorization": "Bearer TOKEN", "X-Test": "1"}, referrer="http://fake/page",
    )  # fmt: skip
    result = await download.run()
    assert result is not None
    assert result.path == tmp_path / "dl" / "Fake Clip [abc].mp4"
    assert result.size == 1400
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    states = [e.state for e in events if isinstance(e, StateChanged)]
    assert states[0] is JobState.PROBING and states[-2:] == [JobState.VERIFYING, JobState.COMPLETED]
    progress = [e for e in events if isinstance(e, Progress)]
    assert progress[-1].downloaded == progress[-1].total == 1400
    (argv,) = calls(tmp_path)
    assert argv[-2:] == ["--", "http://fake/ok"]
    assert "--continue" in argv and f"home:{tmp_path / 'dl'}" in argv
    assert argv[argv.index("--ffmpeg-location") + 1] == str(tools.ffmpeg.parent)  # type: ignore[union-attr]
    assert argv[argv.index("--add-header") : argv.index("--add-header") + 2] == [
        "--add-header",
        "X-Test:1",
    ]
    assert "Bearer TOKEN" not in " ".join(argv)  # auth headers never go on the command line
    cookie_file = Path(argv[argv.index("--cookies") + 1])
    assert not cookie_file.exists()  # deleted after the run
    assert list((tmp_path / "dl").iterdir()) == [result.path]


async def test_user_filename_and_audio_only(tools: ToolPaths, tmp_path: Path) -> None:
    download, _ = make(tools, tmp_path, "http://fake/ok", MediaOptions(quality="audio-mp3"),
                       filename="My Song.mp3")  # fmt: skip
    result = await download.run()
    assert result is not None and result.path.name == "My Song.mp3"
    (argv,) = calls(tmp_path)
    assert argv[argv.index("-o") + 1] == "My Song.%(ext)s"
    assert argv[argv.index("-x") : argv.index("-x") + 3] == ["-x", "--audio-format", "mp3"]


async def test_ffmpeg_required(tmp_path: Path, tools: ToolPaths) -> None:
    no_ffmpeg = ToolPaths(command=tools.command)
    download, events = make(no_ffmpeg, tmp_path, "http://fake/ok")
    with pytest.raises(DownloadError) as exc:
        await download.run()
    assert exc.value.kind is ErrorKind.TOOL_MISSING
    assert any(isinstance(e, Failed) for e in events)


async def test_drm_download_fails_clearly(tools: ToolPaths, tmp_path: Path) -> None:
    download, _ = make(tools, tmp_path, "http://fake/drm")
    with pytest.raises(DownloadError) as exc:
        await download.run()
    assert exc.value.kind is ErrorKind.PROTECTED
    assert download.state is JobState.FAILED


def pause_after(download: MediaDownload, events: list[Event], nbytes: int) -> None:
    fired: list[bool] = []

    def sink(event: Event) -> None:
        events.append(event)
        if isinstance(event, Progress) and event.downloaded >= nbytes and not fired:
            fired.append(True)
            download.pause()

    download._sink = sink


async def test_pause_and_continue(tools: ToolPaths, tmp_path: Path) -> None:
    download, events = make(tools, tmp_path, "http://fake/slow")
    pause_after(download, events, 300)
    assert await download.run() is None
    assert download.state is JobState.PAUSED
    parts = list((tmp_path / "dl").glob("*.part"))
    assert parts and 0 < parts[0].stat().st_size < 1000
    result = await download.run()
    assert result is not None and result.size == 1400  # resumed, nothing written twice
    assert len(calls(tmp_path)) == 2


async def test_cancel_removes_partial_files(tools: ToolPaths, tmp_path: Path) -> None:
    download, events = make(tools, tmp_path, "http://fake/slow")
    pause_after(download, events, 300)
    await download.run()
    download.cancel()
    assert download.state is JobState.CANCELLED
    assert list((tmp_path / "dl").iterdir()) == []


def process_alive(pid: int) -> bool:
    if sys.platform != "win32":
        import os

        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    k32 = ctypes.WinDLL("kernel32")
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(handle, ctypes.byref(code))
    k32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


async def test_pause_also_stops_child_processes(tools: ToolPaths, tmp_path: Path) -> None:
    download, events = make(tools, tmp_path, "http://fake/spawn")
    pause_after(download, events, 200)
    await download.run()
    pid = int((tmp_path / "dl" / "child.pid").read_text())
    for _ in range(50):
        if not process_alive(pid):
            break
        await asyncio.sleep(0.05)
    assert not process_alive(pid)  # the Job Object took the grandchild down too
