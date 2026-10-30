"""Batch URL patterns, URL lists and app settings (no Qt)."""

from pathlib import Path

import pytest

from opendm.core.app_settings import AppSettings, ProxyMode
from opendm.core.batch import BatchError, expand_pattern, parse_url_list


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("http://h/a.zip", ["http://h/a.zip"]),
        (
            "http://h/file[1-3].zip",
            ["http://h/file1.zip", "http://h/file2.zip", "http://h/file3.zip"],
        ),
        ("http://h/f[08-10].z", ["http://h/f08.z", "http://h/f09.z", "http://h/f10.z"]),
        ("http://h/[a-c].txt", ["http://h/a.txt", "http://h/b.txt", "http://h/c.txt"]),
        ("http://h/[1-2]/[x-y]", ["http://h/1/x", "http://h/1/y", "http://h/2/x", "http://h/2/y"]),
        ("http://h/[3-1].bin", ["http://h/3.bin", "http://h/2.bin", "http://h/1.bin"]),
    ],
)
def test_expand_pattern(pattern: str, expected: list[str]) -> None:
    assert expand_pattern(pattern) == expected


@pytest.mark.parametrize(
    "bad", ["http://h/[1-z].zip", "http://h/[a-].zip", "http://h/[1-100000].zip"]
)
def test_expand_pattern_rejects(bad: str) -> None:
    with pytest.raises(BatchError):
        expand_pattern(bad)


def test_parse_url_list() -> None:
    text = """
    # my links
    https://example.com/a.zip
    http://example.com/b[1-2].bin

    not a url
    ftp://example.com/c.iso
    https://example.com/a.zip
    """
    urls, rejected = parse_url_list(text)
    assert urls == [
        "https://example.com/a.zip",
        "http://example.com/b1.bin",
        "http://example.com/b2.bin",
    ]
    assert rejected == ["not a url", "ftp://example.com/c.iso"]


def test_app_settings_round_trip(tmp_path: Path) -> None:
    defaults = AppSettings.defaults(downloads=tmp_path / "dl", data_dir=tmp_path / "data")
    assert defaults.download_dir == tmp_path / "dl"
    assert defaults.tools_dir == tmp_path / "data" / "tools"
    assert defaults.theme == "system" and defaults.close_to_tray and not defaults.first_run_done
    stored = defaults.to_dict()
    changed = AppSettings.from_dict(
        {**stored, "theme": "dark", "connections": 16, "proxy_mode": "manual",
         "proxy_url": "http://proxy:3128", "global_limit": 1000},
        defaults,
    )  # fmt: skip
    assert changed.theme == "dark" and changed.connections == 16
    assert changed.proxy_mode is ProxyMode.MANUAL
    engine = changed.engine_settings()
    assert engine.connections == 16 and engine.proxy == "http://proxy:3128"
    assert not engine.use_system_proxy


def test_app_settings_ignore_bad_values(tmp_path: Path) -> None:
    defaults = AppSettings.defaults(downloads=tmp_path, data_dir=tmp_path)
    loaded = AppSettings.from_dict(
        {"theme": "purple", "connections": 999, "per_host": "x", "unknown": 1}, defaults
    )
    assert loaded.theme == "system"
    assert loaded.connections == defaults.connections
    assert loaded.per_host == defaults.per_host


def test_proxy_modes(tmp_path: Path) -> None:
    base = AppSettings.defaults(downloads=tmp_path, data_dir=tmp_path)
    system = base.engine_settings()
    assert system.use_system_proxy and system.proxy is None
    none = AppSettings.from_dict({"proxy_mode": "none"}, base).engine_settings()
    assert not none.use_system_proxy and none.proxy is None
