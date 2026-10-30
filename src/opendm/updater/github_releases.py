"""Opt-in app update check against GitHub Releases (spec 6.9, decision D65).

Only asks GitHub when the user turned the check on or clicked "Check now". Drafts are never
offered; pre-releases only when the user asked for them. The installer is downloaded next to
the app, checked against the release's ``SHA256SUMS.txt`` and only then handed to the GUI,
which runs it after the user clicks Install. Nothing is installed silently.
"""

import contextlib
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.version import Version, parse_version
from opendm.engine.http.simple import ProgressCallback, fetch_file, get_text
from opendm.engine.http.transport import HttpxTransport, Transport
from opendm.tools.sources import parse_sums

REPO = "Indrajit147/OpenDM"
SUMS_NAME = "SHA256SUMS.txt"
MAX_API_TEXT = 4 * 1024 * 1024


@dataclass(frozen=True)
class UpdateSource:
    api_url: str = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
    # Every installer/checksum link must start with this (the API's asset links are checked).
    download_prefix: str = f"https://github.com/{REPO}/releases/download/"
    page_url: str = f"https://github.com/{REPO}/releases"


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int | None


@dataclass(frozen=True)
class AppUpdate:
    version: Version
    tag: str
    title: str
    notes: str
    page_url: str
    installer: Asset | None
    portable: Asset | None
    sums: Asset | None


def _assets(entry: dict[str, Any]) -> dict[str, Asset]:
    found: dict[str, Asset] = {}
    for item in entry.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name, url, size = item.get("name"), item.get("browser_download_url"), item.get("size")
        if isinstance(name, str) and isinstance(url, str):
            found[name] = Asset(name, url, size if isinstance(size, int) else None)
    return found


def pick_update(releases: list[Any], current: Version, *, prereleases: bool) -> AppUpdate | None:
    """The newest release above ``current`` that the user wants offered, or None."""
    best: AppUpdate | None = None
    for entry in releases:
        if not isinstance(entry, dict) or entry.get("draft") is not False:
            continue
        tag = entry.get("tag_name")
        if not isinstance(tag, str):
            continue
        try:
            version = parse_version(tag)
        except ValueError:
            continue
        if (version.is_prerelease or entry.get("prerelease")) and not prereleases:
            continue
        if version <= current or (best is not None and version <= best.version):
            continue
        assets = _assets(entry)
        best = AppUpdate(
            version=version,
            tag=tag,
            title=str(entry.get("name") or f"OpenDM {version}"),
            notes=str(entry.get("body") or ""),
            page_url=str(entry.get("html_url") or ""),
            installer=assets.get(f"OpenDM-{version}-setup.exe"),
            portable=assets.get(f"OpenDM-{version}-portable.zip"),
            sums=assets.get(SUMS_NAME),
        )
    return best


class Updater:
    def __init__(
        self,
        source: UpdateSource | None = None,
        *,
        transport_factory: Callable[[], Transport] = HttpxTransport,
    ) -> None:
        self.source = source or UpdateSource()
        self._transport_factory = transport_factory

    async def check(self, current: str, *, prereleases: bool) -> AppUpdate | None:
        text = await get_text(
            self._transport_factory(), self.source.api_url,
            {"Accept": "application/vnd.github+json"}, limit=MAX_API_TEXT,
        )  # fmt: skip
        try:
            releases = json.loads(text)
        except ValueError as exc:
            raise DownloadError(ErrorKind.HTTP_CLIENT, "GitHub sent an unreadable answer") from exc
        if not isinstance(releases, list):
            raise DownloadError(ErrorKind.HTTP_CLIENT, "GitHub sent an unexpected answer")
        return pick_update(releases, parse_version(current), prereleases=prereleases)

    async def download(
        self, update: AppUpdate, folder: Path, progress: ProgressCallback | None = None
    ) -> Path:
        """Download and verify the installer; returns its path. Raises if anything is off."""
        installer, sums = update.installer, update.sums
        if installer is None or sums is None:
            raise DownloadError(ErrorKind.NOT_FOUND, "this release has no installer to download")
        for item in (installer, sums):
            if not item.url.startswith(self.source.download_prefix):
                raise DownloadError(
                    ErrorKind.HTTP_CLIENT, f"refusing {item.name}: it is not on the project's page"
                )
        expected = parse_sums(await get_text(self._transport_factory(), sums.url), installer.name)
        if expected is None:
            raise DownloadError(
                ErrorKind.CHECKSUM_MISMATCH, f"{SUMS_NAME} does not list {installer.name}"
            )
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / installer.name
        part = target.with_name(target.name + ".part")
        try:
            await fetch_file(self._transport_factory(), installer.url, part, progress)
            if _sha256(part) != expected:
                raise DownloadError(
                    ErrorKind.CHECKSUM_MISMATCH,
                    "the downloaded installer does not match its published SHA-256; it was deleted",
                )
            os.replace(part, target)
        finally:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
        return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def clean_old_installers(folder: Path, keep: str | None = None) -> None:
    """Delete installers left from earlier updates (the running version no longer needs them)."""
    if not folder.is_dir():
        return
    for path in folder.iterdir():
        leftover = path.name.startswith("OpenDM-") and path.suffix in (".exe", ".part")
        if leftover and path.name != keep:
            with contextlib.suppress(OSError):
                path.unlink()
