"""Where yt-dlp and FFmpeg live (decision D66).

Installed: ``<install folder>\\tools`` (the drive the user chose, removed by the uninstaller).
Portable: ``<exe folder>\\data\\tools``. From source: ``<data folder>\\tools``. Never the
download folder, where a clean-up can delete them by accident.
"""

import contextlib
import os
import shutil
from pathlib import Path

from opendm.core.paths import is_portable

TOOL_FOLDERS = ("yt-dlp", "ffmpeg")


def default_tools_dir(exe_dir: Path | None, data_dir: Path) -> Path:
    if exe_dir is not None and not is_portable(exe_dir):
        return exe_dir / "tools"
    return data_dir / "tools"


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def same_folder(a: Path, b: Path) -> bool:
    return _key(a) == _key(b)


def _inside(path: Path, folder: Path) -> bool:
    p, f = _key(path), _key(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def tools_dir_problem(
    folder: Path, download_dir: Path, downloads: Path | None = None
) -> str | None:
    """Why ``folder`` is a bad place for the tools, or None if it is fine."""
    for name, place in (("download folder", download_dir), ("Downloads folder", downloads)):
        if place is not None and _inside(folder, place):
            return (
                f"Choose a folder outside your {name} ({place}). Tools kept there are easy to "
                "delete by accident when cleaning up downloads."
            )
    return None


def relocate_tools(old: Path, new: Path) -> list[str]:
    """Move the yt-dlp and ffmpeg folders from ``old`` to ``new``; returns what was moved.

    Only those two folders move; anything else in ``old`` stays. An existing folder in
    ``new`` is never overwritten (that tool stays where it was).
    """
    if same_folder(old, new):
        return []
    moved = []
    for name in TOOL_FOLDERS:
        source, target = old / name, new / name
        if not source.is_dir() or target.exists():
            continue
        new.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(target))
        except OSError:
            with contextlib.suppress(OSError):  # a half-copied folder must not look installed
                if source.is_dir():
                    shutil.rmtree(target)
            continue
        moved.append(name)
    return moved
