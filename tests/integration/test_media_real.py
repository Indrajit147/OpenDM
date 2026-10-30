"""M5 acceptance with the real yt-dlp and FFmpeg against local fixtures.

Runs only when OPENDM_TEST_TOOLS points at a folder with yt-dlp\\yt-dlp.exe and
ffmpeg\\bin\\ffmpeg.exe (and ffprobe.exe), e.g. ``set OPENDM_TEST_TOOLS=D:\\Tools``.
Fixtures are generated on first use by scripts/make_media_fixtures.py.
"""

import importlib.util
import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.events import Event, Progress
from opendm.core.models import DownloadRequest, JobState
from opendm.core.settings import EngineSettings
from opendm.engine.media.download import MediaDownload
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import ToolPaths, analyze
from tests.server.app import FaultServer

TOOLS = os.environ.get("OPENDM_TEST_TOOLS")
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "media"
pytestmark = [
    pytest.mark.tools,
    pytest.mark.skipif(not TOOLS, reason="set OPENDM_TEST_TOOLS to run with the real tools"),
]


@pytest.fixture(scope="module")
def tools() -> ToolPaths:
    base = Path(TOOLS or ".")
    paths = ToolPaths(
        ytdlp=base / "yt-dlp" / "yt-dlp.exe", ffmpeg=base / "ffmpeg" / "bin" / "ffmpeg.exe"
    )
    if not (FIXTURES / "dash" / "manifest.mpd").exists():
        spec = importlib.util.spec_from_file_location(
            "fixtures", ROOT / "scripts" / "make_media_fixtures.py"
        )
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        module.make(paths.ffmpeg)
    return paths


@pytest.fixture
def media(server: FaultServer, tools: ToolPaths) -> Iterator[FaultServer]:
    server.static_root = FIXTURES
    yield server
    server.static_root = None


def probe(tools: ToolPaths, path: Path) -> dict:
    assert tools.ffmpeg is not None
    ffprobe = tools.ffmpeg.with_name("ffprobe.exe")
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "stream=codec_type,codec_name",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    data = json.loads(out)
    return {
        "types": sorted(s["codec_type"] for s in data["streams"]),
        "codecs": sorted(s["codec_name"] for s in data["streams"]),
        "duration": float(data["format"]["duration"]),
    }


async def download(
    tools: ToolPaths, url: str, dest: Path, options: MediaOptions | None = None,
    events: list[Event] | None = None,
) -> MediaDownload:  # fmt: skip
    job = MediaDownload(
        DownloadRequest(url, dest), options or MediaOptions(), tools=tools,
        temp_dir=dest / "tmp", settings=EngineSettings(progress_interval=0.0),
        sink=(events if events is not None else []).append,
    )  # fmt: skip
    return job


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("/static/clip.mp4", "clip"),
        ("/static/hls/index.m3u8", "index"),
        ("/static/dash/manifest.mpd", "manifest"),  # separate video + audio: FFmpeg merges
    ],
)
async def test_download_and_merge(
    media, tools: ToolPaths, tmp_path: Path, path: str, name: str
) -> None:
    job = await download(tools, media.url(path), tmp_path)
    result = await job.run()
    assert result is not None and result.path.suffix == ".mp4"
    assert result.path.parent == tmp_path and name in result.path.name
    info = probe(tools, result.path)
    assert info["types"] == ["audio", "video"]
    assert 4.5 <= info["duration"] <= 5.6
    assert not [p for p in tmp_path.iterdir() if p.suffix in (".part", ".ytdl")]


async def test_audio_only_mp3(media, tools: ToolPaths, tmp_path: Path) -> None:
    job = await download(tools, media.url("/static/hls/index.m3u8"), tmp_path,
                         MediaOptions(quality="audio-mp3"))  # fmt: skip
    result = await job.run()
    assert result is not None and result.path.suffix == ".mp3"
    info = probe(tools, result.path)
    assert info["types"] == ["audio"] and info["codecs"] == ["mp3"]


async def test_analyze_page_and_subtitles(media, tools: ToolPaths, tmp_path: Path) -> None:
    url = media.url("/static/page.html")
    info = await analyze(tools, DownloadRequest(url, tmp_path), temp_dir=tmp_path)
    assert "en" in info.subtitles
    job = await download(tools, url, tmp_path, MediaOptions(subtitles=("en",)))
    result = await job.run()
    assert result is not None
    srt = list(tmp_path.glob("*.srt"))
    assert srt and "Hello from OpenDM" in srt[0].read_text("utf-8")


@pytest.mark.parametrize("path", ["/static/hls_drm/index.m3u8", "/static/dash_drm/manifest.mpd"])
async def test_protected_content_is_refused(
    media, tools: ToolPaths, tmp_path: Path, path: str
) -> None:
    with pytest.raises(DownloadError) as exc:
        await analyze(tools, DownloadRequest(media.url(path), tmp_path), temp_dir=tmp_path)
    assert exc.value.kind is ErrorKind.PROTECTED
    assert "not supported" in exc.value.message
    job = await download(tools, media.url(path), tmp_path / "dl")
    with pytest.raises(DownloadError) as exc:
        await job.run()
    assert exc.value.kind is ErrorKind.PROTECTED
    assert not (tmp_path / "dl").exists() or not any((tmp_path / "dl").glob("*.mp4"))


async def test_pause_and_resume(media, tools: ToolPaths, tmp_path: Path) -> None:
    events: list[Event] = []
    job = await download(tools, media.url("/static/clip.mp4?rate=25K"), tmp_path, events=events)

    def sink(event: Event) -> None:
        events.append(event)
        if (
            isinstance(event, Progress)
            and event.downloaded > 20_000
            and job.state is JobState.DOWNLOADING
        ):
            job.pause()

    job._sink = sink
    assert await job.run() is None
    assert job.state is JobState.PAUSED
    job._sink = events.append
    result = await job.run()
    assert result is not None
    assert probe(tools, result.path)["types"] == ["audio", "video"]
