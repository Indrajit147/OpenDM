"""yt-dlp as a subprocess (decision D5): page analysis and shared command-line options."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.models import DownloadRequest
from opendm.core.redact import SECRET_HEADERS
from opendm.engine.media.cookies import temporary_cookie_file
from opendm.engine.media.drm import PROTECTED_MESSAGE, info_is_protected
from opendm.engine.media.formats import available_heights
from opendm.engine.media.process import run_tool
from opendm.engine.media.progress import classify_ytdlp_error

ANALYZE_TIMEOUT = 180.0


@dataclass(frozen=True)
class ToolPaths:
    ytdlp: Path | None = None
    ffmpeg: Path | None = None  # ffmpeg.exe; ffprobe.exe is expected next to it
    command: tuple[str, ...] | None = None  # replaces the yt-dlp executable (tests)

    def ytdlp_command(self) -> list[str]:
        if self.command:
            return list(self.command)
        if self.ytdlp is None or not self.ytdlp.is_file():
            raise DownloadError(ErrorKind.TOOL_MISSING, "yt-dlp is not installed")
        return [str(self.ytdlp)]

    def ffmpeg_available(self) -> bool:
        return self.ffmpeg is not None and self.ffmpeg.is_file()


@dataclass(frozen=True)
class MediaEntry:
    url: str
    title: str
    duration: float | None = None


@dataclass
class MediaInfo:
    url: str
    title: str
    id: str = ""
    duration: float | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    extractor: str | None = None
    heights: list[int] = field(default_factory=list)
    subtitles: list[str] = field(default_factory=list)
    auto_subtitles: list[str] = field(default_factory=list)
    entries: list[MediaEntry] = field(default_factory=list)

    @property
    def is_playlist(self) -> bool:
        return bool(self.entries)


def request_args(
    request: DownloadRequest, *, proxy: str | None, use_system_proxy: bool, cookie_file: Path | None
) -> list[str]:
    """Network options shared by analysis and download."""
    args: list[str] = []
    if proxy:
        args += ["--proxy", proxy]
    elif not use_system_proxy:
        args += ["--proxy", ""]  # empty string: no proxy at all
    if request.user_agent:
        args += ["--user-agent", request.user_agent]
    if request.referrer:
        args += ["--referer", request.referrer]
    for name, value in request.headers.items():
        if name.lower() not in SECRET_HEADERS | {"user-agent", "referer"}:
            args += ["--add-header", f"{name}:{value}"]
    if cookie_file is not None:
        args += ["--cookies", str(cookie_file)]
    if not request.verify_tls:
        args.append("--no-check-certificates")
    return args


def summarize(info: dict[str, Any], fallback_url: str) -> MediaInfo:
    if info.get("_type") == "playlist":
        entries = [
            MediaEntry(
                url=e.get("webpage_url") or e.get("url") or "",
                title=e.get("title") or e.get("id") or "?",
                duration=e.get("duration"),
            )
            for e in info.get("entries") or []
            if e and (e.get("webpage_url") or e.get("url"))
        ]
        return MediaInfo(
            url=info.get("webpage_url") or fallback_url,
            title=info.get("title") or "Playlist",
            id=str(info.get("id") or ""),
            uploader=info.get("uploader"),
            extractor=info.get("extractor"),
            entries=entries,
        )
    return MediaInfo(
        url=info.get("webpage_url") or fallback_url,
        title=info.get("title") or info.get("id") or "video",
        id=str(info.get("id") or ""),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        uploader=info.get("uploader"),
        extractor=info.get("extractor"),
        heights=available_heights(info.get("formats") or []),
        subtitles=sorted(info.get("subtitles") or {}),
        auto_subtitles=sorted(info.get("automatic_captions") or {}),
    )


async def analyze(
    tools: ToolPaths,
    request: DownloadRequest,
    *,
    temp_dir: Path,
    proxy: str | None = None,
    use_system_proxy: bool = True,
) -> MediaInfo:
    """``yt-dlp -J --flat-playlist``: what is on the page. Raises PROTECTED for DRM."""
    command = tools.ytdlp_command()
    with temporary_cookie_file(request.cookies, request.url, temp_dir) as cookies:
        args = [
            *command, "-J", "--flat-playlist", "--no-warnings", "--encoding", "utf-8",
            *request_args(request, proxy=proxy, use_system_proxy=use_system_proxy,
                          cookie_file=cookies),
            "--", request.url,
        ]  # fmt: skip
        code, out, err = await run_tool(args, timeout=ANALYZE_TIMEOUT)
    if code != 0:
        raise classify_ytdlp_error(err)
    try:
        info = json.loads(out)
    except ValueError as exc:
        raise DownloadError(ErrorKind.MEDIA, "yt-dlp returned unreadable data") from exc
    if info_is_protected(info):
        raise DownloadError(ErrorKind.PROTECTED, PROTECTED_MESSAGE)
    return summarize(info, request.url)


async def tool_version(command: list[str], flag: str = "--version") -> str | None:
    """First line of ``<tool> --version`` (FFmpeg: ``-version``), or None if it fails."""
    try:
        code, out, _ = await run_tool([*command, flag], timeout=30)
    except (OSError, TimeoutError):
        return None
    if code != 0 or not out.strip():
        return None
    return out.strip().splitlines()[0]
