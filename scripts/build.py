r"""Build OpenDM for Windows: icon, PyInstaller folder, portable ZIP, installer.

Run from the repo root (or use scripts\build.cmd):
    .venv\Scripts\python.exe scripts\build.py [--no-installer] [--iscc PATH]

Output (git-ignored): dist\OpenDM\ (the programs), dist\OpenDM-<version>-portable.zip and
dist\OpenDM-<version>-setup.exe. Work files go to build\.
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
DEFAULT_ISCC = Path(r"D:\Tools\InnoSetup\ISCC.exe")
sys.path.insert(0, str(ROOT / "src"))

from opendm import __version__  # noqa: E402
from opendm.core.paths import PORTABLE_FLAG  # noqa: E402
from opendm.core.version import parse_version  # noqa: E402


def make_icon() -> Path:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from opendm.gui.icons import write_ico

    _app = QGuiApplication.instance() or QGuiApplication([])
    return write_ico(BUILD / "opendm.ico")


def pyinstaller() -> Path:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
         str(ROOT / "installer" / "opendm.spec")],
        check=True, cwd=ROOT,
        # PyInstaller's cache would otherwise go to %LOCALAPPDATA% on C:.
        env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(BUILD / "pyinstaller-cache")},
    )  # fmt: skip
    return DIST / "OpenDM"


def portable_zip(app_dir: Path) -> Path:
    """The same folder plus portable.flag: data stays next to the programs."""
    target = DIST / f"OpenDM-{__version__}-portable.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                z.write(path, Path("OpenDM") / path.relative_to(app_dir))
        z.writestr(f"OpenDM/{PORTABLE_FLAG}", "OpenDM keeps its data next to the programs.\r\n")
    return target


def installer(iscc: Path) -> Path:
    subprocess.run(
        [str(iscc), "/Qp", f"/DAppVersion={__version__}",
         f"/DFileVersion={parse_version(__version__).windows}", f"/DSourceDir={DIST / 'OpenDM'}",
         f"/DIconFile={BUILD / 'opendm.ico'}", f"/O{DIST}",
         str(ROOT / "installer" / "opendm.iss")],
        check=True, cwd=ROOT,
    )  # fmt: skip
    return DIST / f"OpenDM-{__version__}-setup.exe"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OpenDM")
    parser.add_argument("--no-installer", action="store_true")
    parser.add_argument("--iscc", type=Path, default=DEFAULT_ISCC)
    args = parser.parse_args()

    shutil.rmtree(DIST / "OpenDM", ignore_errors=True)
    print("icon:", make_icon())
    app_dir = pyinstaller()
    print("programs:", app_dir)
    print("portable:", portable_zip(app_dir))
    if not args.no_installer:
        if not args.iscc.is_file():
            print(f"Inno Setup not found at {args.iscc}; skipping the installer", file=sys.stderr)
            return 1
        print("installer:", installer(args.iscc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
