"""Tool manager against a fake GitHub release / FFmpeg site on the test server."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from opendm.core.errors import DownloadError, ErrorKind
from opendm.tools.manager import ToolManager
from opendm.tools.sources import Sources, parse_sums
from tests.server.app import FaultServer

NEW = b"NEW-YTDLP" * 1000
VERSIONS = {
    b"NEW-YTDLP": "2099.01.01",
    b"OLD-YTDLP": "2000.01.01",
    b"FFMPEG": "ffmpeg version 9.0.2",
    b"FFPROBE": "ffprobe version 9.0.2",
}


async def fake_probe(path: Path) -> str | None:
    data = path.read_bytes()
    return next((v for prefix, v in VERSIONS.items() if data.startswith(prefix)), None)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def release(server: FaultServer, tmp_path: Path):
    root = tmp_path / "static"
    (root / "rel").mkdir(parents=True)
    (root / "api").mkdir()
    (root / "ffmpeg").mkdir()
    (root / "rel" / "yt-dlp.exe").write_bytes(NEW)
    (root / "rel" / "SHA2-256SUMS").write_text(
        f"{sha(b'x')}  yt-dlp_linux\n{sha(NEW)}  yt-dlp.exe\n"
    )
    api = {
        "tag_name": "2099.01.01",
        "assets": [
            {"name": "yt-dlp.exe", "size": len(NEW),
             "browser_download_url": server.url("/static/rel/yt-dlp.exe")},
            {"name": "SHA2-256SUMS", "size": 100,
             "browser_download_url": server.url("/static/rel/SHA2-256SUMS")},
        ],
    }  # fmt: skip
    (root / "api" / "latest.json").write_text(json.dumps(api))
    zip_path = root / "ffmpeg" / "ffmpeg.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe", b"FFMPEG-binary")
        z.writestr("ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe", b"FFPROBE-binary")
        z.writestr("ffmpeg-9.0.2-essentials_build/bin/ffplay.exe", b"not wanted")
        z.writestr("ffmpeg-9.0.2-essentials_build/LICENSE", "GPL")
        z.writestr("../evil.exe", b"zip-slip attempt")
    (root / "ffmpeg" / "ffmpeg.zip.sha256").write_text(sha(zip_path.read_bytes()))
    (root / "ffmpeg" / "release-version").write_text("9.0.2")
    server.static_root = root
    sources = Sources(
        ytdlp_api=server.url("/static/api/latest.json"),
        ytdlp_download_prefix=server.url("/static/rel/"),
        ffmpeg_zip=server.url("/static/ffmpeg/ffmpeg.zip"),
        ffmpeg_sha256=server.url("/static/ffmpeg/ffmpeg.zip.sha256"),
        ffmpeg_version=server.url("/static/ffmpeg/release-version"),
    )
    yield root, sources, api
    server.static_root = None


def manager(tmp_path: Path, sources: Sources) -> ToolManager:
    return ToolManager(tmp_path / "tools", sources=sources, version_probe=fake_probe)


def test_parse_sums() -> None:
    text = "aa  yt-dlp\nBB *yt-dlp.exe\n# comment\n"
    assert parse_sums(text, "yt-dlp.exe") == "bb"
    assert parse_sums(text, "missing.exe") is None
    assert parse_sums("cc", None) == "cc"  # a .sha256 file with just the hash


async def test_status_before_install(tmp_path: Path, release) -> None:
    _, sources, _ = release
    status = {t.name: t for t in await manager(tmp_path, sources).status()}
    assert not status["yt-dlp"].installed and not status["ffmpeg"].installed
    assert status["yt-dlp"].path == tmp_path / "tools" / "yt-dlp" / "yt-dlp.exe"


async def test_install_ytdlp(tmp_path: Path, release) -> None:
    _, sources, _ = release
    tools = manager(tmp_path, sources)
    latest = await tools.latest_ytdlp()
    assert (latest.version, latest.size) == ("2099.01.01", len(NEW))
    seen: list[tuple[int, int | None]] = []
    info = await tools.install_ytdlp(lambda done, total: seen.append((done, total)))
    assert info.installed and info.version == "2099.01.01"
    assert tools.ytdlp_path.read_bytes() == NEW
    assert seen and seen[-1] == (len(NEW), len(NEW))
    assert sorted(p.name for p in tools.ytdlp_path.parent.iterdir()) == ["yt-dlp.exe"]
    assert tools.paths().ytdlp == tools.ytdlp_path


async def test_update_keeps_a_backup(tmp_path: Path, release) -> None:
    _, sources, _ = release
    tools = manager(tmp_path, sources)
    tools.ytdlp_path.parent.mkdir(parents=True)
    tools.ytdlp_path.write_bytes(b"OLD-YTDLP")
    assert await tools.ytdlp_update_available() == ("2000.01.01", "2099.01.01")
    await tools.install_ytdlp()
    assert tools.ytdlp_path.read_bytes() == NEW
    assert tools.ytdlp_path.with_suffix(".exe.old").read_bytes() == b"OLD-YTDLP"
    assert await tools.ytdlp_update_available() is None


async def test_checksum_mismatch_leaves_old_tool(tmp_path: Path, release) -> None:
    root, sources, _ = release
    (root / "rel" / "SHA2-256SUMS").write_text(f"{sha(b'other')}  yt-dlp.exe\n")
    tools = manager(tmp_path, sources)
    tools.ytdlp_path.parent.mkdir(parents=True)
    tools.ytdlp_path.write_bytes(b"OLD-YTDLP")
    with pytest.raises(DownloadError) as exc:
        await tools.install_ytdlp()
    assert exc.value.kind is ErrorKind.CHECKSUM_MISMATCH
    assert tools.ytdlp_path.read_bytes() == b"OLD-YTDLP"
    assert sorted(p.name for p in tools.ytdlp_path.parent.iterdir()) == ["yt-dlp.exe"]


async def test_foreign_download_url_rejected(tmp_path: Path, release) -> None:
    root, sources, api = release
    api["assets"][0]["browser_download_url"] = "https://evil.example/yt-dlp.exe"
    (root / "api" / "latest.json").write_text(json.dumps(api))
    with pytest.raises(DownloadError) as exc:
        await manager(tmp_path, sources).latest_ytdlp()
    assert "unexpected download location" in exc.value.message


async def test_broken_update_is_rolled_back(tmp_path: Path, release) -> None:
    root, sources, _ = release
    broken = b"BROKEN" * 10
    (root / "rel" / "yt-dlp.exe").write_bytes(broken)
    (root / "rel" / "SHA2-256SUMS").write_text(f"{sha(broken)}  yt-dlp.exe\n")
    tools = manager(tmp_path, sources)
    tools.ytdlp_path.parent.mkdir(parents=True)
    tools.ytdlp_path.write_bytes(b"OLD-YTDLP")
    with pytest.raises(DownloadError) as exc:
        await tools.install_ytdlp()
    assert "does not run" in exc.value.message
    assert tools.ytdlp_path.read_bytes() == b"OLD-YTDLP"


async def test_install_ffmpeg_extracts_only_the_two_programs(tmp_path: Path, release) -> None:
    _, sources, _ = release
    tools = manager(tmp_path, sources)
    release_info = await tools.ffmpeg_release()
    assert release_info.version == "9.0.2" and release_info.size and release_info.size > 0
    info = await tools.install_ffmpeg()
    assert info.installed and info.version == "ffmpeg version 9.0.2"
    files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()
                   and "static" not in p.parts)  # fmt: skip
    assert files == [
        str(Path("tools/ffmpeg/LICENSE.txt")),
        str(Path("tools/ffmpeg/bin/ffmpeg.exe")),
        str(Path("tools/ffmpeg/bin/ffprobe.exe")),
    ]
    assert not (tmp_path / "evil.exe").exists()


async def test_use_existing(tmp_path: Path, release) -> None:
    _, sources, _ = release
    existing = tmp_path / "elsewhere" / "yt-dlp.exe"
    existing.parent.mkdir()
    existing.write_bytes(b"OLD-YTDLP")
    tools = manager(tmp_path, sources)
    info = await tools.use_existing("yt-dlp", existing)
    assert info.path == existing and info.version == "2000.01.01"
    assert tools.paths().ytdlp == existing
    with pytest.raises(ValueError):
        await tools.use_existing("yt-dlp", tmp_path / "nope.exe")
    junk = tmp_path / "junk.exe"
    junk.write_bytes(b"not a tool")
    with pytest.raises(ValueError):
        await tools.use_existing("ffmpeg", junk)


@pytest.mark.live
async def test_real_github_latest_release(tmp_path: Path) -> None:
    latest = await ToolManager(tmp_path).latest_ytdlp()
    assert latest.url.startswith("https://github.com/yt-dlp/yt-dlp/releases/download/")
