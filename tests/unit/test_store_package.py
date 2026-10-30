"""Store ZIP of the extension: no dev key, no tests, same version as the app (M9)."""

import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "package_extension", ROOT / "scripts" / "package_extension.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_store_zip(tmp_path: Path) -> None:
    target = _module().package(tmp_path, version="1.2.3")
    assert target.name == "opendm-extension-1.2.3.zip"
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
        manifest = json.loads(z.read("manifest.json"))
    assert "key" not in manifest  # the store gives the extension its own ID
    assert manifest["version"] == "1.2.3"
    assert not any(n.startswith("tests/") or n.endswith((".mjs", ".gitkeep")) for n in names)
    assert {"background.js", "content.js", "popup/popup.html", "icons/icon128.png"} <= set(names)
    source = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert "key" in source  # the unpacked dev copy keeps its fixed ID


def test_store_version_drops_the_prerelease_part(tmp_path: Path) -> None:
    # Chrome versions are 1-4 numbers only.
    target = _module().package(tmp_path, version="1.0.0-rc.1")
    with zipfile.ZipFile(target) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["version"] == "1.0.0" and manifest["version_name"] == "1.0.0-rc.1"
