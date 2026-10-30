r"""Smoke-test the built programs from the portable ZIP (run after scripts\build.py).

    .venv\Scripts\python.exe scripts\smoke_dist.py

Unpacks dist\OpenDM-<version>-portable.zip into build\smoke and checks, against the local
test server and a private IPC pipe (nothing touches your installed OpenDM or its data):
  opendm-cli   --version, a standalone download with the right SHA-256
  opendm-host  status without the app ("unavailable"), --status
  OpenDM.exe   starts hidden in portable mode, answers through the host and the CLI, quits
"""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from opendm import __version__  # noqa: E402
from opendm.core.paths import database_path  # noqa: E402
from opendm.ipc import client as ipc_client  # noqa: E402
from opendm.storage.db import Database  # noqa: E402
from opendm.storage.repositories import SettingsRepository  # noqa: E402
from tests.server.app import FaultServer, content_sha256  # noqa: E402

SMOKE = ROOT / "build" / "smoke"
NO_WINDOW = 0x08000000


def check(condition: bool, what: str) -> None:
    print(("ok   " if condition else "FAIL ") + what)
    if not condition:
        raise SystemExit(1)


def run(args: list, env: dict, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(a) for a in args], env=env, capture_output=True, timeout=120,
        creationflags=NO_WINDOW, **kw,
    )  # fmt: skip


def host_message(host: Path, env: dict, message: dict) -> dict:
    data = json.dumps(message).encode()
    origin = "chrome-extension://pjkejmcidaikllfpgmfginpahcockofb/"
    out = run([host, origin], env, input=struct.pack("<I", len(data)) + data).stdout
    (length,) = struct.unpack("<I", out[:4])
    return json.loads(out[4 : 4 + length])


def main() -> int:
    archive = ROOT / "dist" / f"OpenDM-{__version__}-portable.zip"
    check(archive.is_file(), f"portable ZIP exists ({archive.name})")
    shutil.rmtree(SMOKE, ignore_errors=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(SMOKE)
    app = SMOKE / "OpenDM"
    cli, host, gui = app / "opendm-cli.exe", app / "opendm-host.exe", app / "OpenDM.exe"
    check((app / "portable.flag").is_file(), "portable.flag is in the ZIP")
    check((app / "extension" / "manifest.json").is_file(), "extension folder is included")
    check(not (app / "extension" / "tests").exists(), "extension tests are left out")
    check((app / "licenses" / "LGPL-3.0.txt").is_file(), "Qt license text is included")

    pipe = f"opendm-smoke-{uuid.uuid4().hex[:8]}"
    env = {**os.environ, "OPENDM_IPC_NAME": pipe, "OPENDM_HOST_WAIT": "0"}
    env.pop("OPENDM_HOST_LAUNCH", None)

    result = run([cli, "--version"], env, text=True)
    check(__version__ in result.stdout, f"opendm-cli --version says {__version__}")

    with FaultServer() as server:
        out = SMOKE / "downloads"
        result = run(
            [cli, "get", server.url("/file/smoke.bin?size=3M"), "-o", out, "--standalone", "-q"],
            env, text=True,
        )  # fmt: skip
        file = out / "smoke.bin"
        ok = result.returncode == 0 and file.is_file()
        check(ok, f"opendm-cli standalone download ({result.stderr.strip()[-200:]})")
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        check(digest == content_sha256(3 * 1024 * 1024, 1), "downloaded file has the right SHA-256")

    reply = host_message(host, env, {"type": "status"})
    check(reply.get("error") == "unavailable", "opendm-host: no app -> unavailable")
    result = run([host, "--status"], env, text=True)
    check(result.returncode == 0 and "Chrome" in result.stdout, "opendm-host --status runs")

    # Skip the first-run wizard so nothing shows on screen.
    data = app / "data"
    db = Database(database_path(data))
    SettingsRepository(db).set("first_run_done", True)
    db.close()

    proc = subprocess.Popen([gui, "--minimized"], env=env)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if host_message(host, env, {"type": "status"}).get("ok"):
                break
            time.sleep(0.5)
        else:
            check(False, "OpenDM.exe answers through opendm-host within 30 s")
        check(True, "OpenDM.exe answers through opendm-host")
        result = run([cli, "list"], env, text=True)
        check(result.returncode == 0, "opendm-cli list talks to the running app")
        check(database_path(data).is_file(), "portable mode keeps data next to the programs")
        ipc_client.request("quit", {}, name=pipe, timeout=5)
        check(proc.wait(timeout=20) == 0, "OpenDM.exe quits cleanly on request")
    finally:
        if proc.poll() is None:
            proc.kill()
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
