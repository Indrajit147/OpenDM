"""Temporary Netscape cookie file for yt-dlp (spec 6.2).

Created in the app's own data folder (per-user), readable by the owner only, deleted
when the job ends. Values are never logged.
"""

import contextlib
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

HEADER = "# Netscape HTTP Cookie File"
_FORBIDDEN = set("\t\r\n")


def _pairs(cookie_header: str) -> list[tuple[str, str]]:
    pairs = []
    for part in cookie_header.split(";"):
        name, sep, value = part.strip().partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name or _FORBIDDEN & set(name + value):
            continue
        pairs.append((name, value))
    return pairs


@contextlib.contextmanager
def temporary_cookie_file(
    cookie_header: str | None, url: str, folder: Path
) -> Iterator[Path | None]:
    """Write ``Cookie:`` header values for the URL's host; yields None if there are none."""
    pairs = _pairs(cookie_header) if cookie_header else []
    if not pairs:
        yield None
        return
    parts = urlsplit(url)
    host = parts.hostname or ""
    secure = "TRUE" if parts.scheme == "https" else "FALSE"
    lines = [HEADER, "# Written by OpenDM for one download; deleted afterwards."]
    lines += [f"{host}\tFALSE\t/\t{secure}\t0\t{name}\t{value}" for name, value in pairs]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"cookies-{secrets.token_hex(8)}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        yield path
    finally:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
