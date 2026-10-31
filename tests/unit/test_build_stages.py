"""scripts/build.py stages, so CI can sign the programs before packaging them (M10)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def build(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("build_script", ROOT / "scripts" / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[str] = []
    app = tmp_path / "OpenDM"
    monkeypatch.setattr(module, "DIST", tmp_path)
    monkeypatch.setattr(module, "make_icon", lambda: calls.append("icon") or tmp_path / "i.ico")
    monkeypatch.setattr(module, "pyinstaller", lambda: calls.append("pyinstaller") or app)
    monkeypatch.setattr(module, "portable_zip", lambda d: calls.append("zip") or tmp_path / "z")
    monkeypatch.setattr(module, "installer", lambda iscc: calls.append("installer") or tmp_path)
    iscc = tmp_path / "ISCC.exe"
    iscc.write_bytes(b"")
    module.calls, module.app, module.iscc = calls, app, iscc
    return module


def test_all_is_the_default(build) -> None:
    assert build.main(["--iscc", str(build.iscc)]) == 0
    assert build.calls == ["icon", "pyinstaller", "zip", "installer"]


def test_programs_stage_only_builds_the_programs(build) -> None:
    assert build.main(["--stage", "programs"]) == 0
    assert build.calls == ["icon", "pyinstaller"]


def test_package_stage_reuses_the_signed_programs(build) -> None:
    build.app.mkdir()
    (build.app / "OpenDM.exe").write_bytes(b"signed")
    assert build.main(["--stage", "package", "--iscc", str(build.iscc)]) == 0
    assert build.calls == ["zip", "installer"]
    assert (build.app / "OpenDM.exe").read_bytes() == b"signed"  # not rebuilt


def test_package_stage_needs_the_programs(build) -> None:
    assert build.main(["--stage", "package", "--iscc", str(build.iscc)]) == 1
    assert build.calls == []
