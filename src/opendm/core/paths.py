"""Locations of the app's own data (database, logs, settings).

Partial downloads never live here; they sit next to their target file (spec 6.10).
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from opendm.core.branding import APP_NAME

PORTABLE_FLAG = "portable.flag"


def default_exe_dir() -> Path | None:
    """Directory of the frozen executable, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def is_portable(exe_dir: Path) -> bool:
    """True if ``portable.flag`` exists next to the executable."""
    return (exe_dir / PORTABLE_FLAG).is_file()


def app_data_dir(
    exe_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the app data directory without creating it.

    Portable mode stores data in ``<exe_dir>/data``. Otherwise data goes to
    ``%LOCALAPPDATA%\\OpenDM``, falling back to ``~/.local/share/OpenDM`` off Windows.
    """
    env = os.environ if environ is None else environ
    if exe_dir is not None and is_portable(exe_dir):
        return exe_dir / "data"
    local = env.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME
