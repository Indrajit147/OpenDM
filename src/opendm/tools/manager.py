"""Tool manager: install, verify and update yt-dlp and FFmpeg (spec 6.8).

Downloads only from the official locations in ``sources``, verifies the published
SHA-256 before anything replaces an existing tool, keeps the previous version as
``*.old`` and rolls back if the new one does not run. The GUI asks for consent first.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from opendm.core.errors import DownloadError, ErrorKind, error_from_status
from opendm.engine.http.transport import HttpxTransport, Transport
from opendm.engine.media.ytdlp import ToolPaths, tool_version
from opendm.tools.sources import YTDLP_ASSET, YTDLP_SUMS, Sources, parse_sums

ProgressCallback = Callable[[int, int | None], None]
VersionProbe = Callable[[Path], Awaitable[str | None]]
_WANTED = ("ffmpeg.exe", "ffprobe.exe")
MAX_TEXT = 1024 * 1024


@dataclass(frozen=True)
class ToolInfo:
    name: str
    path: Path
    installed: bool
    version: str | None


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int | None
    checksum_url: str


async def default_probe(path: Path) -> str | None:
    flag = "-version" if path.stem.lower() in ("ffmpeg", "ffprobe") else "--version"
    return await tool_version([str(path)], flag)


class ToolManager:
    def __init__(
        self,
        folder: Path,
        *,
        sources: Sources | None = None,
        overrides: dict[str, Path] | None = None,
        transport_factory: Callable[[], Transport] = HttpxTransport,
        version_probe: VersionProbe = default_probe,
    ) -> None:
        self.folder = folder
        self.sources = sources or Sources()
        self.overrides = dict(overrides or {})
        self._transport_factory = transport_factory
        self._probe = version_probe

    # --- paths & status -------------------------------------------------------------------------

    @property
    def ytdlp_path(self) -> Path:
        return self.overrides.get("yt-dlp") or self.folder / "yt-dlp" / "yt-dlp.exe"

    @property
    def ffmpeg_path(self) -> Path:
        return self.overrides.get("ffmpeg") or self.folder / "ffmpeg" / "bin" / "ffmpeg.exe"

    def paths(self) -> ToolPaths:
        return ToolPaths(ytdlp=self.ytdlp_path, ffmpeg=self.ffmpeg_path)

    async def info(self, name: str) -> ToolInfo:
        path = self.ytdlp_path if name == "yt-dlp" else self.ffmpeg_path
        version = await self._probe(path) if path.is_file() else None
        return ToolInfo(name, path, version is not None, version)

    async def status(self) -> list[ToolInfo]:
        return [await self.info("yt-dlp"), await self.info("ffmpeg")]

    async def use_existing(self, name: str, path: Path) -> ToolInfo:
        """Point at a copy the user already has; it must exist and run."""
        if name not in ("yt-dlp", "ffmpeg"):
            raise ValueError(f"unknown tool {name}")
        if not path.is_file():
            raise ValueError(f"{path} does not exist")
        version = await self._probe(path)
        if version is None:
            raise ValueError(f"{path} does not look like {name}")
        self.overrides[name] = path
        return ToolInfo(name, path, True, version)

    # --- releases ----------------------------------------------------------------------------------

    async def latest_ytdlp(self) -> Release:
        data = json.loads(await self._get_text(self.sources.ytdlp_api))
        assets = {a.get("name"): a for a in data.get("assets", []) if isinstance(a, dict)}
        exe, sums = assets.get(YTDLP_ASSET), assets.get(YTDLP_SUMS)
        if not exe or not sums:
            raise DownloadError(ErrorKind.MEDIA, "the yt-dlp release has no Windows build")
        for url in (exe["browser_download_url"], sums["browser_download_url"]):
            if not str(url).startswith(self.sources.ytdlp_download_prefix):
                raise DownloadError(ErrorKind.HTTP_CLIENT, f"unexpected download location: {url}")
        return Release(str(data["tag_name"]), exe["browser_download_url"], exe.get("size"),
                       sums["browser_download_url"])  # fmt: skip

    async def ffmpeg_release(self) -> Release:
        version = (await self._get_text(self.sources.ffmpeg_version)).strip()
        size = await self._content_length(self.sources.ffmpeg_zip)
        return Release(version, self.sources.ffmpeg_zip, size, self.sources.ffmpeg_sha256)

    async def ytdlp_update_available(self) -> tuple[str | None, str] | None:
        """(installed, latest) if an update exists, else None."""
        current = (await self.info("yt-dlp")).version
        latest = (await self.latest_ytdlp()).version
        if current is not None and current.strip() == latest:
            return None
        return current, latest

    # --- installing -----------------------------------------------------------------------------------

    async def install_ytdlp(self, progress: ProgressCallback | None = None) -> ToolInfo:
        release = await self.latest_ytdlp()
        expected = parse_sums(await self._get_text(release.checksum_url), YTDLP_ASSET)
        if expected is None:
            raise DownloadError(ErrorKind.CHECKSUM_MISMATCH, "no checksum published for yt-dlp")
        target = self.ytdlp_path
        target.parent.mkdir(parents=True, exist_ok=True)
        new = target.with_name(target.name + ".download")
        try:
            await self._fetch(release.url, new, progress)
            self._verify(new, expected, "yt-dlp")
            await self._swap_in(new, target, "yt-dlp")
        finally:
            with contextlib.suppress(OSError):
                new.unlink(missing_ok=True)
        return await self.info("yt-dlp")

    async def install_ffmpeg(self, progress: ProgressCallback | None = None) -> ToolInfo:
        release = await self.ffmpeg_release()
        expected = parse_sums(await self._get_text(release.checksum_url), None)
        if expected is None:
            raise DownloadError(ErrorKind.CHECKSUM_MISMATCH, "no checksum published for FFmpeg")
        bin_dir = self.ffmpeg_path.parent
        bin_dir.mkdir(parents=True, exist_ok=True)
        archive = bin_dir.parent / "ffmpeg-download.zip"
        extracted: list[Path] = []
        try:
            await self._fetch(release.url, archive, progress)
            self._verify(archive, expected, "FFmpeg")
            extracted = await asyncio.to_thread(self._extract_ffmpeg, archive, bin_dir)
            for new in extracted:
                await self._swap_in(new, new.with_suffix(""), "FFmpeg")
        finally:
            for leftover in (archive, *extracted):
                with contextlib.suppress(OSError):
                    leftover.unlink(missing_ok=True)
        return await self.info("ffmpeg")

    @staticmethod
    def _extract_ffmpeg(archive: Path, bin_dir: Path) -> list[Path]:
        """Copy only bin/ffmpeg.exe and bin/ffprobe.exe (+ the license) to fixed paths."""
        written: list[Path] = []
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                parts = entry.filename.replace("\\", "/").split("/")
                if len(parts) == 3 and parts[1] == "bin" and parts[2] in _WANTED:
                    out = bin_dir / (parts[2] + ".new")
                elif len(parts) == 2 and parts[1] == "LICENSE":
                    out = bin_dir.parent / "LICENSE.txt"
                else:
                    continue
                with z.open(entry) as src, open(out, "wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                if out.suffix == ".new":
                    written.append(out)
        if sorted(p.stem for p in written) != sorted(_WANTED):
            raise DownloadError(ErrorKind.MEDIA, "the FFmpeg archive does not contain ffmpeg.exe")
        return written

    # --- helpers -----------------------------------------------------------------------------------------

    @staticmethod
    def _verify(path: Path, expected: str, name: str) -> None:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected.lower():
            raise DownloadError(
                ErrorKind.CHECKSUM_MISMATCH,
                f"{name} download does not match its published SHA-256; it was not installed",
            )

    async def _swap_in(self, new: Path, target: Path, name: str) -> None:
        """Replace ``target`` with ``new``, keeping ``target.old``; roll back if it won't run."""
        backup = target.with_name(target.name + ".old")
        had_old = target.exists()
        if had_old:
            os.replace(target, backup)
        os.replace(new, target)
        if await self._probe(target) is None:
            target.unlink(missing_ok=True)
            if had_old:
                os.replace(backup, target)
            raise DownloadError(ErrorKind.MEDIA, f"the new {name} does not run; kept the old one")

    async def _get_text(self, url: str) -> str:
        transport = self._transport_factory()
        try:
            async with transport.stream("GET", url) as resp:
                if not 200 <= resp.status < 300:
                    raise error_from_status(resp.status)
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_TEXT:
                        raise DownloadError(ErrorKind.HTTP_CLIENT, "response too large")
                return body.decode("utf-8", errors="replace")
        finally:
            await transport.aclose()

    async def _content_length(self, url: str) -> int | None:
        transport = self._transport_factory()
        try:
            async with transport.stream("HEAD", url) as resp:
                value = resp.headers.get("content-length")
                return int(value) if value and value.isdigit() else None
        except DownloadError:
            return None
        finally:
            await transport.aclose()

    async def _fetch(self, url: str, dest: Path, progress: ProgressCallback | None) -> None:
        transport = self._transport_factory()
        try:
            async with transport.stream("GET", url) as resp:
                if not 200 <= resp.status < 300:
                    raise error_from_status(resp.status)
                length = resp.headers.get("content-length")
                total = int(length) if length and length.isdigit() else None
                done = 0
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        await asyncio.to_thread(f.write, chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, total)
        finally:
            await transport.aclose()
