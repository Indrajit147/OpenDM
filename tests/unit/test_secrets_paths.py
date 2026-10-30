"""DPAPI secrets and the Windows Downloads folder."""

import sys
from pathlib import Path

import pytest

from opendm.core import paths, secrets

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


@windows_only
def test_protect_round_trip() -> None:
    data = b"odm_session=s3cr3t; Authorization: Bearer xyz"
    blob = secrets.protect(data)
    assert blob != data
    assert b"s3cr3t" not in blob
    assert secrets.unprotect(blob) == data


@windows_only
def test_unprotect_rejects_garbage() -> None:
    with pytest.raises(secrets.SecretsError):
        secrets.unprotect(b"not a dpapi blob")


@windows_only
def test_available_on_windows() -> None:
    assert secrets.available()


def test_unavailable_elsewhere(monkeypatch) -> None:
    monkeypatch.setattr(secrets.sys, "platform", "linux")
    assert not secrets.available()
    with pytest.raises(secrets.SecretsError):
        secrets.protect(b"x")


@windows_only
def test_downloads_dir_is_the_known_folder() -> None:
    folder = paths.downloads_dir()
    assert folder.is_absolute()
    assert folder.exists()


def test_downloads_dir_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.downloads_dir() == tmp_path / "Downloads"
