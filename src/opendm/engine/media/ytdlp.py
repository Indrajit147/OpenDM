"""yt-dlp as a subprocess (decision D5): page analysis and shared command-line options."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.models import DownloadRequest
from opendm.core.redact import SECRET_HEADERS
from opendm.engine.http.transport import HttpxTransport
from opendm.engine.media.cookies import temporary_cookie_file
from opendm.engine.media.drm import (
    PROTECTED_MESSAGE,
    dash_is_protected,
    hls_is_protected,
    info_is_protected,
)
from opendm.engine.media.formats import available_heights
from opendm.engine.media.process import run_tool
from opendm.engine.media.progress import classify_ytdlp_error, formats_hidden

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
    info = await _page_info(tools, request, temp_dir, proxy, use_system_proxy, request.cookies)
    if request.cookies and info.get("_type") != "playlist" and not has_streams(info):
        # Browser cookies can hide the streams (see formats_hidden); try without them.
        info = await _page_info(tools, request, temp_dir, proxy, use_system_proxy, None)
    if info_is_protected(info):
        raise DownloadError(ErrorKind.PROTECTED, PROTECTED_MESSAGE)
    # yt-dlp does not flag every DRM scheme (e.g. Widevine ContentProtection in DASH),
    # so read the stream manifests ourselves.
    manifests = {request.url} if looks_like_manifest(request.url) else set()
    manifests |= {f["manifest_url"] for f in info.get("formats") or [] if f.get("manifest_url")}
    for manifest in sorted(manifests)[:MAX_MANIFEST_CHECKS]:
        await check_manifest(manifest, request, proxy=proxy, use_system_proxy=use_system_proxy)
    return summarize(info, request.url)


async def _page_info(
    tools: ToolPaths,
    request: DownloadRequest,
    temp_dir: Path,
    proxy: str | None,
    use_system_proxy: bool,
    cookie_header: str | None,
) -> dict[str, Any]:
    with temporary_cookie_file(cookie_header, request.url, temp_dir) as cookies:
        args = [
            *tools.ytdlp_command(), "-J", "--flat-playlist", "--no-warnings",
            "--encoding", "utf-8",
            *request_args(request, proxy=proxy, use_system_proxy=use_system_proxy,
                          cookie_file=cookies),
            "--", request.url,
        ]  # fmt: skip
        code, out, err = await run_tool(args, timeout=ANALYZE_TIMEOUT)
    if code != 0:
        if cookie_header and formats_hidden(err):
            return await _page_info(tools, request, temp_dir, proxy, use_system_proxy, None)
        raise classify_ytdlp_error(err)
    try:
        return json.loads(out)
    except ValueError as exc:
        raise DownloadError(ErrorKind.MEDIA, "yt-dlp returned unreadable data") from exc


def has_streams(info: dict[str, Any]) -> bool:
    """True if any format has audio or video (not only thumbnails/storyboards)."""
    formats = info.get("formats")
    if not formats:
        return bool(info.get("url"))  # a single direct format without a list
    # Storyboards say "none" for both; formats without codec details count as media.
    return any(f.get("vcodec") != "none" or f.get("acodec") != "none" for f in formats)


MAX_MANIFEST_CHECKS = 5
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MANIFEST_TYPES = ("mpegurl", "dash+xml")


def looks_like_manifest(url: str) -> bool:
    return urlsplit(url).path.lower().endswith((".m3u8", ".mpd"))


async def check_manifest(
    url: str, request: DownloadRequest, *, proxy: str | None = None, use_system_proxy: bool = True
) -> None:
    """Fetch an HLS/DASH manifest and raise PROTECTED if it signals DRM.

    Fetch problems are ignored here: yt-dlp reports them properly during the download.
    """
    transport = HttpxTransport(
        verify=request.verify_tls, proxy=proxy, use_system_proxy=use_system_proxy
    )
    headers = request.request_headers()
    try:
        async with transport.stream("GET", url, headers) as resp:
            content_type = resp.headers.get("content-type", "").lower()
            if not 200 <= resp.status < 300:
                return
            if not (looks_like_manifest(url) or any(t in content_type for t in _MANIFEST_TYPES)):
                return
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > MAX_MANIFEST_BYTES:
                    return
    except DownloadError:
        return
    finally:
        await transport.aclose()
    text = body.decode("utf-8", errors="replace")
    if hls_is_protected(text) or dash_is_protected(text):
        raise DownloadError(ErrorKind.PROTECTED, PROTECTED_MESSAGE)


async def tool_version(command: list[str], flag: str = "--version") -> str | None:
    """First line of ``<tool> --version`` (FFmpeg: ``-version``), or None if it fails."""
    try:
        code, out, _ = await run_tool([*command, flag], timeout=30)
    except (OSError, TimeoutError):
        return None
    if code != 0 or not out.strip():
        return None
    return out.strip().splitlines()[0]
