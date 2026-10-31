"""Registering the Native Messaging host for Chrome and Edge (portable build, Settings, M7).

Tests use their own keys under HKCU\\Software\\OpenDM-tests, never the browsers' real ones.
"""

import contextlib
import json
import sys
import uuid
from pathlib import Path

import pytest

from opendm.core.branding import EXTENSION_IDS, NATIVE_HOST_NAME
from opendm.host import register as reg

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")


@pytest.fixture
def browsers():
    import winreg

    base = rf"Software\OpenDM-tests\{uuid.uuid4().hex[:8]}"
    keys = {"Chrome": rf"{base}\Chrome", "Edge": rf"{base}\Edge"}
    yield keys
    subkeys = [rf"{path}\{NATIVE_HOST_NAME}" for path in keys.values()]
    for sub in (*subkeys, *keys.values(), base, r"Software\OpenDM-tests"):
        with contextlib.suppress(OSError):  # missing, or the parent still has other tests' keys
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)


def read_default(path: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{path}\{NATIVE_HOST_NAME}") as key:
            return winreg.QueryValue(key, None)
    except FileNotFoundError:
        return None


def fake_host(tmp_path: Path) -> Path:
    host = tmp_path / "app" / "opendm-host.exe"
    host.parent.mkdir()
    host.write_bytes(b"MZ")
    return host


def test_manifest_content(tmp_path: Path) -> None:
    host = fake_host(tmp_path)
    data = reg.host_manifest(host)
    assert data == {
        "name": NATIVE_HOST_NAME,
        "description": "OpenDM download manager",
        "path": str(host),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{i}/" for i in EXTENSION_IDS],
    }


def test_unpacked_and_edge_store_extensions_are_allowed(tmp_path: Path) -> None:
    origins = reg.host_manifest(fake_host(tmp_path))["allowed_origins"]
    assert "chrome-extension://pjkejmcidaikllfpgmfginpahcockofb/" in origins  # unpacked (key)
    assert "chrome-extension://bionffckkflcblecfgnclbndjflemgld/" in origins  # Edge Add-ons
    assert all(len(i) == 32 and set(i) <= set("abcdefghijklmnop") for i in EXTENSION_IDS)


def test_register_writes_manifest_and_keys(tmp_path: Path, browsers) -> None:
    host = fake_host(tmp_path)
    manifest = reg.register(host, host.parent, browsers=browsers)
    assert manifest == host.parent / f"{NATIVE_HOST_NAME}.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["path"] == str(host)
    for path in browsers.values():
        assert read_default(path) == str(manifest)
    assert reg.status(browsers=browsers) == {"Chrome": manifest, "Edge": manifest}


def test_status_reports_missing_and_broken(tmp_path: Path, browsers) -> None:
    assert reg.status(browsers=browsers) == {"Chrome": None, "Edge": None}
    host = fake_host(tmp_path)
    reg.register(host, host.parent, browsers=browsers)
    host.unlink()  # the app folder was moved or deleted: the registration is useless
    assert reg.status(browsers=browsers) == {"Chrome": None, "Edge": None}


def test_unregister_removes_keys_and_manifest(tmp_path: Path, browsers) -> None:
    host = fake_host(tmp_path)
    manifest = reg.register(host, host.parent, browsers=browsers)
    reg.unregister(browsers=browsers, manifest_dir=host.parent)
    assert not manifest.exists()
    assert all(read_default(path) is None for path in browsers.values())
    reg.unregister(browsers=browsers, manifest_dir=host.parent)  # twice is fine


def test_dev_launcher_runs_python_with_a_console(tmp_path: Path) -> None:
    launcher = reg.dev_launcher(tmp_path)
    text = launcher.read_text(encoding="utf-8")
    assert launcher.suffix == ".cmd"
    assert "-m opendm.host" in text
    assert "pythonw" not in text.lower()  # needs real stdin/stdout


def test_real_browser_keys_are_hkcu_paths() -> None:
    assert reg.BROWSERS == {
        "Chrome": r"Software\Google\Chrome\NativeMessagingHosts",
        "Edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    }


def test_host_command_line(tmp_path: Path, browsers, monkeypatch, capsys) -> None:
    from opendm.host.__main__ import main

    host = fake_host(tmp_path)
    monkeypatch.setattr(reg, "BROWSERS", browsers)
    monkeypatch.setattr(reg, "registration_target", lambda: (host, host.parent))
    assert main(["--register"]) == 0
    assert "Chrome" in capsys.readouterr().out
    assert read_default(browsers["Edge"]) is not None
    assert main(["--status"]) == 0
    assert "registered" in capsys.readouterr().out
    assert main(["--unregister"]) == 0
    assert read_default(browsers["Edge"]) is None
