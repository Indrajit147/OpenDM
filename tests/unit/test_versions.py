"""Version numbers (with pre-releases), the changelog and release notes (M8)."""

import importlib.util
import re
from pathlib import Path

import pytest

from opendm import __version__
from opendm.core.version import Version, parse_version

ROOT = Path(__file__).resolve().parents[2]


def _release_notes_module():
    path = ROOT / "scripts" / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.7.0", "0.8.0"),
        ("0.9.0", "0.10.0"),
        ("0.8.0-rc.1", "0.8.0"),
        ("0.8.0-rc.1", "0.8.0-rc.2"),
        ("0.8.0-rc.9", "0.8.0-rc.10"),
        ("0.8.0-beta.1", "0.8.0-rc.1"),
        ("0.8.0-alpha.1", "0.8.0-beta.1"),
        ("0.8.0", "0.8.1-rc.1"),
        ("1.0.0", "v1.0.1"),  # tags carry a leading v
    ],
)
def test_version_order(older: str, newer: str) -> None:
    assert parse_version(older) < parse_version(newer)
    assert parse_version(newer) > parse_version(older)


def test_version_parts() -> None:
    v = parse_version("v0.8.0-rc.2")
    assert v == Version(0, 8, 0, "rc", 2)
    assert v.is_prerelease and str(v) == "0.8.0-rc.2"
    assert v.base == "0.8.0" and v.windows == "0.8.0.0"
    assert not parse_version("1.2.3").is_prerelease
    assert parse_version("1.2.3") == parse_version("v1.2.3")


@pytest.mark.parametrize(
    "text", ["", "1.2", "1.2.3.4", "1.2.3-rc", "1.2.3-dev.1", "x1.2.3", "1.2.3 "]
)
def test_bad_versions_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_version(text)


def test_app_version_is_valid() -> None:
    assert str(parse_version(__version__)) == __version__


CHANGELOG = """# Changelog

## [Unreleased]
- Something later.

## [0.8.0] - 2026-10-31
### Added
- Updates.

### Fixed
- A bug.

## [0.7.0] - 2026-10-30
- Installer.
"""


def test_release_notes_for_a_version() -> None:
    notes = _release_notes_module().release_notes(CHANGELOG, "0.8.0")
    assert notes == "### Added\n- Updates.\n\n### Fixed\n- A bug."


def test_release_notes_for_a_prerelease_use_the_final_section() -> None:
    notes = _release_notes_module().release_notes(CHANGELOG, "v0.8.0-rc.2")
    assert notes.startswith("### Added")
    assert "Installer" not in notes


def test_release_notes_missing_section() -> None:
    with pytest.raises(LookupError):
        _release_notes_module().release_notes(CHANGELOG, "0.9.0")


def test_changelog_covers_the_current_version() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert _release_notes_module().release_notes(text, __version__).strip()
    assert re.search(r"^## \[0\.7\.0\]", text, re.M)
