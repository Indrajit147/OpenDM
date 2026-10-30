from pathlib import Path

from opendm.core import branding, paths


def test_default_uses_localappdata(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    assert paths.app_data_dir(exe_dir=None, environ=env) == tmp_path / "Local" / branding.APP_NAME


def test_portable_flag_puts_data_next_to_exe(tmp_path: Path) -> None:
    (tmp_path / paths.PORTABLE_FLAG).write_text("")
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    assert paths.is_portable(tmp_path)
    assert paths.app_data_dir(exe_dir=tmp_path, environ=env) == tmp_path / "data"


def test_exe_dir_without_flag_is_not_portable(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    assert not paths.is_portable(tmp_path)
    assert paths.app_data_dir(exe_dir=tmp_path, environ=env) == tmp_path / "Local" / "OpenDM"


def test_falls_back_to_home_without_localappdata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    expected = tmp_path / ".local" / "share" / branding.APP_NAME
    assert paths.app_data_dir(exe_dir=None, environ={}) == expected
