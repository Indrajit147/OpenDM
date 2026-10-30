r"""Install, check, reinstall (upgrade path) and uninstall OpenDM silently for this user.

    .venv\Scripts\python.exe scripts\installer_test.py

Installs dist\OpenDM-<version>-setup.exe into build\install-test\OpenDM (not the default
folder), checks files, Start menu shortcut, uninstall entry and the Chrome/Edge registration,
then uninstalls and checks that nothing is left. Your data in %LOCALAPPDATA%\OpenDM is never
deleted (a silent uninstall keeps it). The browser registration of a dev checkout is replaced
during the test, so the script runs scripts\register_host_dev.cmd again at the end if it was
registered before.
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opendm import __version__  # noqa: E402
from opendm.core.branding import NATIVE_HOST_NAME  # noqa: E402
from opendm.host.register import BROWSERS  # noqa: E402

APP_ID = "{862F85C1-3E08-4A1C-B8A0-F6BDA0393A80}_is1"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
TARGET = ROOT / "build" / "install-test"
APP = TARGET / "OpenDM"
SHORTCUT = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\OpenDM.lnk"
DATA = Path(os.environ["LOCALAPPDATA"]) / "OpenDM"
NO_WINDOW = 0x08000000


def check(condition: bool, what: str) -> None:
    print(("ok   " if condition else "FAIL ") + what)
    if not condition:
        raise SystemExit(1)


def key_value(path: str, name: str | None = None) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name or "")[0]
    except FileNotFoundError:
        return None


def host_keys() -> list[str | None]:
    return [key_value(rf"{base}\{NATIVE_HOST_NAME}") for base in BROWSERS.values()]


def install(setup: Path, log: str) -> None:
    result = subprocess.run(
        [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={APP}",
         f"/LOG={TARGET / log}"],
        timeout=300,
    )  # fmt: skip
    check(result.returncode == 0, f"setup exits with 0 ({log})")


def check_installed() -> None:
    for name in ("OpenDM.exe", "opendm-cli.exe", "opendm-host.exe", "unins000.exe",
                 "LICENSE", r"licenses\LGPL-3.0.txt", r"extension\manifest.json"):  # fmt: skip
        check((APP / name).is_file(), f"installed {name}")
    check(not (APP / "portable.flag").exists(), "installed copy is not portable")
    check(SHORTCUT.is_file(), "Start menu shortcut")
    check(key_value(UNINSTALL_KEY, "DisplayVersion") == __version__, "uninstall entry (HKCU)")
    manifest = APP / f"{NATIVE_HOST_NAME}.json"
    check(manifest.is_file(), "Native Messaging manifest written by opendm-host --register")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    check(Path(data["path"]) == APP / "opendm-host.exe", "manifest points at the installed host")
    check(host_keys() == [str(manifest)] * 2, "Chrome and Edge registry keys point at it")

    env = {**os.environ, "OPENDM_IPC_NAME": f"opendm-itest-{uuid.uuid4().hex[:8]}",
           "OPENDM_HOST_WAIT": "0"}  # fmt: skip
    env.pop("OPENDM_HOST_LAUNCH", None)
    out = subprocess.run([str(APP / "opendm-cli.exe"), "--version"], capture_output=True,
                         text=True, env=env, creationflags=NO_WINDOW).stdout  # fmt: skip
    check(__version__ in out, "installed opendm-cli runs")
    message = json.dumps({"type": "status"}).encode()
    out = subprocess.run(
        [str(APP / "opendm-host.exe"), "chrome-extension://pjkejmcidaikllfpgmfginpahcockofb/"],
        input=struct.pack("<I", len(message)) + message, capture_output=True, env=env,
        creationflags=NO_WINDOW, timeout=60,
    ).stdout  # fmt: skip
    reply = json.loads(out[4 : 4 + struct.unpack("<I", out[:4])[0]])
    check(reply.get("error") == "unavailable", "installed opendm-host answers the browser")


def uninstall() -> None:
    # The uninstaller restarts itself from a temp copy, so wait for the folder to go away.
    subprocess.run([str(APP / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                   timeout=300)  # fmt: skip
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and (APP / "unins000.exe").exists():
        time.sleep(0.5)
    time.sleep(2)


def main() -> int:
    setup = ROOT / "dist" / f"OpenDM-{__version__}-setup.exe"
    check(setup.is_file(), f"installer exists ({setup.name})")
    check(key_value(UNINSTALL_KEY, "DisplayName") is None, "OpenDM is not installed already")
    dev_registered = any(host_keys())
    data_before = DATA.exists()
    shutil.rmtree(TARGET, ignore_errors=True)
    TARGET.mkdir(parents=True)
    try:
        install(setup, "install.log")
        check_installed()
        install(setup, "upgrade.log")  # same version again: the upgrade path
        check_installed()
        uninstall()
        leftovers = [str(p.relative_to(APP)) for p in APP.rglob("*")] if APP.exists() else []
        check(not leftovers, f"no files left in the install folder {leftovers[:5]}")
        check(not SHORTCUT.exists(), "Start menu shortcut removed")
        check(key_value(UNINSTALL_KEY, "DisplayName") is None, "uninstall entry removed")
        check(host_keys() == [None, None], "Chrome and Edge registry keys removed")
        check(DATA.exists() == data_before, "your OpenDM data folder is untouched")
    finally:
        if dev_registered:
            subprocess.run(["cmd", "/d", "/c", str(ROOT / "scripts" / "register_host_dev.cmd")],
                           check=False, capture_output=True)  # fmt: skip
            print("dev browser registration restored")
    print("installer test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
