"""Turn untrusted names (from servers, URLs, users) into safe Windows filenames."""

import os
import re
import sys
import unicodedata
from pathlib import Path

from opendm.core.branding import PARTIAL_SUFFIX
from opendm.core.errors import DownloadError, ErrorKind

DEFAULT_NAME = "download"
MAX_COMPONENT = 255  # NTFS limit, in UTF-16 code units
MAX_EXT_LEN = 16
LEGACY_MAX_PATH = 259  # MAX_PATH (260) minus the terminating NUL

_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{dev}{n}" for dev in ("COM", "LPT") for n in [*"123456789", "¹", "²", "³"]}
)
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')
_SEPARATORS = re.compile(r"[\\/]")


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_ext(name: str) -> tuple[str, str]:
    """Split off a plausible extension (short, no spaces); dotfiles have none."""
    stem, ext = os.path.splitext(name)
    if not ext or len(ext) > MAX_EXT_LEN or " " in ext:
        return name, ""
    return stem, ext


def _truncate_utf16(text: str, budget: int) -> str:
    while utf16_len(text) > budget:
        text = text[:-1]
    return text


def sanitize_filename(name: str, default: str = DEFAULT_NAME) -> str:
    """Return a single safe path component, or ``default`` if nothing usable is left.

    Drops any directory part (path traversal), replaces characters Windows forbids,
    strips trailing dots/spaces, defuses reserved device names and limits the
    length to 255 UTF-16 units while keeping the extension.
    """
    name = unicodedata.normalize("NFC", name)
    parts = [p for p in _SEPARATORS.split(name) if p.strip(" .")]
    name = parts[-1] if parts else ""
    name = _ILLEGAL.sub("_", name).strip(" ").rstrip(". ")
    if not name.strip("."):
        return default

    first = name.split(".")[0]
    if first.rstrip(" ").upper() in _RESERVED:
        name = first + "_" + name[len(first) :]

    if utf16_len(name) > MAX_COMPONENT:
        stem, ext = split_ext(name)
        stem = _truncate_utf16(stem, MAX_COMPONENT - utf16_len(ext)).rstrip(". ")
        name = (stem or DEFAULT_NAME) + ext
    return name


def max_path_length() -> int:
    """Longest usable path: 259 unless Windows long paths are enabled."""
    if sys.platform != "win32":
        return 4096
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    except OSError:
        return LEGACY_MAX_PATH
    return 32_000 if enabled == 1 else LEGACY_MAX_PATH


def fit_to_path(directory: Path, name: str, limit: int | None = None) -> str:
    """Shorten the stem so ``directory/name`` plus the partial suffix fits ``limit``."""
    limit = max_path_length() if limit is None else limit
    excess = len(str(directory / (name + PARTIAL_SUFFIX))) - limit
    if excess <= 0:
        return name
    stem, ext = split_ext(name)
    stem = stem[: len(stem) - excess].rstrip(". ")
    if not stem:
        raise DownloadError(
            ErrorKind.PATH_TOO_LONG, f"folder path is too long for any filename: {directory}"
        )
    return stem + ext


def unique_path(directory: Path, name: str) -> Path:
    """``directory/name``, or ``name (1).ext``, ``name (2).ext``... if taken.

    A name counts as taken if the file or its in-progress partial file exists.
    """

    def taken(path: Path) -> bool:
        return path.exists() or path.with_name(path.name + PARTIAL_SUFFIX).exists()

    candidate = directory / name
    stem, ext = split_ext(name)
    n = 1
    while taken(candidate):
        candidate = directory / f"{stem} ({n}){ext}"
        n += 1
    return candidate
