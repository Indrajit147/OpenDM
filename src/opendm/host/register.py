"""Register the Native Messaging host with Chrome and Edge for the current user (no admin).

The installer writes the same keys itself; this module serves the portable build
(``opendm-host.exe --register``) and Settings -> Browser.
"""

import contextlib
import json
import sys
from pathlib import Path

from opendm.core.branding import EXTENSION_IDS, HOST_EXE, NATIVE_HOST_NAME
from opendm.core.paths import app_data_dir, default_exe_dir

# HKCU subkeys under which each browser looks for hosts.
BROWSERS: dict[str, str] = {
    "Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
}


def host_manifest(host_path: Path) -> dict:
    return {
        "name": NATIVE_HOST_NAME,
        "description": "OpenDM download manager",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{i}/" for i in EXTENSION_IDS],
    }


def manifest_path(folder: Path) -> Path:
    return folder / f"{NATIVE_HOST_NAME}.json"


def register(
    host_path: Path, manifest_dir: Path, *, browsers: dict[str, str] | None = None
) -> Path:
    import winreg

    manifest = manifest_path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(host_manifest(host_path), indent=2), encoding="utf-8")
    for base in (browsers or BROWSERS).values():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NATIVE_HOST_NAME}") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, str(manifest))
    return manifest


def unregister(*, browsers: dict[str, str] | None = None, manifest_dir: Path | None = None) -> None:
    import winreg

    for base in (browsers or BROWSERS).values():
        with contextlib.suppress(FileNotFoundError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NATIVE_HOST_NAME}")
    if manifest_dir is not None:
        manifest_path(manifest_dir).unlink(missing_ok=True)


def _registered_manifest(base: str) -> Path | None:
    """The manifest a browser would load, if it and the host it names exist."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NATIVE_HOST_NAME}") as key:
            manifest = Path(winreg.QueryValue(key, None))
        host = Path(json.loads(manifest.read_text(encoding="utf-8"))["path"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return manifest if host.is_file() else None


def status(*, browsers: dict[str, str] | None = None) -> dict[str, Path | None]:
    return {name: _registered_manifest(base) for name, base in (browsers or BROWSERS).items()}


def dev_launcher(folder: Path) -> Path:
    """From source there is no opendm-host.exe: a .cmd runs the host with this Python."""
    python = Path(sys.executable).with_name("python.exe")  # pythonw has no usable stdio
    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / "opendm-host.cmd"
    launcher.write_text(f'@echo off\r\n"{python}" -m opendm.host %*\r\n', encoding="utf-8")
    return launcher


def extension_dir() -> Path:
    """The unpacked extension shipped with this copy (the repo's folder when run from source)."""
    exe_dir = default_exe_dir()
    if exe_dir is not None:
        return exe_dir / "extension"
    return Path(__file__).resolve().parents[3] / "extension"


def registration_target() -> tuple[Path, Path]:
    """(host program, folder for the manifest) for this copy of OpenDM."""
    exe_dir = default_exe_dir()
    if exe_dir is not None:
        return exe_dir / HOST_EXE, exe_dir
    folder = app_data_dir(None) / "native-host"
    return dev_launcher(folder), folder
