r"""Build the extension ZIP for the Chrome Web Store and Edge Add-ons.

    .venv\Scripts\python.exe scripts\package_extension.py

Writes build\store\opendm-extension-<version>.zip from extension\ without the development
"key" (the stores assign their own extension ID; the unpacked copy keeps its fixed ID for
development), without tests, and with the app's version.
"""

import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "extension"
SKIP_DIRS = {"tests"}
SKIP_SUFFIXES = {".mjs", ".gitkeep"}


def _app_version() -> str:
    text = (ROOT / "src" / "opendm" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    assert match is not None
    return match.group(1)


def package(out_dir: Path, version: str | None = None) -> Path:
    version = version or _app_version()
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("key", None)
    numbers = re.match(r"\d+(\.\d+){0,3}", version)
    assert numbers is not None, version
    manifest["version"] = numbers.group(0)
    if numbers.group(0) != version:
        manifest["version_name"] = version  # shown to users; Chrome versions are numbers only
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"opendm-extension-{version}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(SOURCE.rglob("*")):
            rel = path.relative_to(SOURCE)
            skipped = path.suffix in SKIP_SUFFIXES or path.name in SKIP_SUFFIXES
            if path.is_dir() or rel.parts[0] in SKIP_DIRS or skipped:
                continue
            if rel.as_posix() == "manifest.json":
                z.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            else:
                z.write(path, rel.as_posix())
    return target


if __name__ == "__main__":
    print(package(ROOT / "build" / "store"))
    sys.exit(0)
