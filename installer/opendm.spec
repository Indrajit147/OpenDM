# PyInstaller spec: one folder (dist\OpenDM) with OpenDM.exe, opendm-cli.exe, opendm-host.exe.
# Build with scripts\build.cmd (it makes build\opendm.ico first). Decision D11: onedir.
# ruff: noqa
import re
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
BUILD = ROOT / "build"
ICON = str(BUILD / "opendm.ico")
VERSION = re.search(r'__version__ = "([\d.]+)"', (SRC / "opendm" / "__init__.py").read_text()).group(1)
NUMBERS = tuple(int(x) for x in VERSION.split(".")) + (0,)

QT_ONLY = ["PySide6", "shiboken6"]
# Not used anywhere in OpenDM; keeps the folder smaller.
UNUSED = ["tkinter", "unittest", "pydoc_data", "lib2to3", "test", "pytest", "_pytest"]


def version_info(exe: str, description: str) -> VSVersionInfo:
    strings = [
        StringStruct("CompanyName", "Indrajit Gupta"),
        StringStruct("FileDescription", description),
        StringStruct("FileVersion", VERSION),
        StringStruct("InternalName", Path(exe).stem),
        StringStruct("LegalCopyright", "Copyright (C) 2026 Indrajit Gupta. GPL-3.0-or-later."),
        StringStruct("OriginalFilename", exe),
        StringStruct("ProductName", "OpenDM"),
        StringStruct("ProductVersion", VERSION),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=NUMBERS, prodvers=NUMBERS),
        kids=[
            StringFileInfo([StringTable("040904B0", strings)]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


def analysis(entry: str, excludes: list[str]) -> Analysis:
    return Analysis(
        [str(ROOT / "installer" / entry)],
        pathex=[str(SRC)],
        datas=collect_data_files("opendm", includes=["**/*.sql"]),
        excludes=UNUSED + excludes,
        noarchive=False,
    )


def exe(a: Analysis, name: str, description: str, console: bool) -> EXE:
    return EXE(
        PYZ(a.pure),
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        icon=ICON,
        version=version_info(f"{name}.exe", description),
        console=console,
        upx=False,
    )


gui = analysis("entry_gui.py", [])
cli = analysis("entry_cli.py", QT_ONLY)
host = analysis("entry_host.py", QT_ONLY)


def keep(entry) -> bool:
    """Leave out Qt parts OpenDM does not use (about 27 MB)."""
    dest = entry[0].replace("\\", "/").lower()
    return not (dest.endswith("/opengl32sw.dll")  # software OpenGL; widgets do not need it
                or "pyside6/translations/" in dest)  # Qt's own UI translations; English only


coll = COLLECT(
    exe(gui, "OpenDM", "OpenDM download manager", console=False),
    exe(cli, "opendm-cli", "OpenDM command line", console=True),
    exe(host, "opendm-host", "OpenDM browser connector", console=True),
    [e for e in gui.binaries + cli.binaries + host.binaries if keep(e)],
    [e for e in gui.datas + cli.datas + host.datas if keep(e)],
    name="OpenDM",
    upx=False,
)

# Next to the programs: licenses and the unpacked browser extension (without its tests).
dist = Path(DISTPATH) / "OpenDM"
for name in ("LICENSE", "THIRD_PARTY_LICENSES.md"):
    shutil.copy2(ROOT / name, dist / name)
shutil.copytree(ROOT / "installer" / "licenses", dist / "licenses", dirs_exist_ok=True)
shutil.copytree(
    ROOT / "extension",
    dist / "extension",
    ignore=shutil.ignore_patterns("tests", "*.mjs"),
    dirs_exist_ok=True,
)
