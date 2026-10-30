"""Log files with secrets removed, and the diagnostics ZIP (spec 6.11, M9)."""

import json
import logging
import zipfile
from pathlib import Path

import pytest

from opendm.core.logs import LOG_NAME, export_diagnostics, redact_text, setup_logging

SECRET_URL = "https://cdn.example.com/file.zip?token=SECRET123&sig=abc"


def test_redact_text() -> None:
    text = (
        f"GET {SECRET_URL} failed; Cookie: SID=SECRETCOOKIE; a=b\n"
        "authorization=Bearer SECRETTOKEN\nproxy http://user:SECRETPW@proxy.lan:8080/ ok"
    )
    clean = redact_text(text)
    for secret in ("SECRET123", "SECRETCOOKIE", "SECRETTOKEN", "SECRETPW", "sig=abc"):
        assert secret not in clean
    assert "https://cdn.example.com/file.zip?<redacted>" in clean
    assert "proxy.lan:8080" in clean  # the host stays: it helps to read the log


@pytest.fixture
def log_dir(tmp_path: Path):
    folder = tmp_path / "logs"
    setup_logging(folder, max_bytes=2000, backups=2)
    yield folder
    setup_logging(None)  # detach the file handler again


def test_log_file_is_written_without_secrets(log_dir: Path) -> None:
    logging.getLogger("opendm.test").info("download %s started", SECRET_URL)
    logging.getLogger("opendm.test").warning("headers: Cookie: SID=SECRETCOOKIE")
    text = (log_dir / LOG_NAME).read_text(encoding="utf-8")
    assert "download https://cdn.example.com/file.zip?<redacted> started" in text
    assert "SECRET" not in text
    assert "WARNING" in text and "opendm.test" in text


def test_logs_rotate(log_dir: Path) -> None:
    for i in range(200):
        logging.getLogger("opendm.test").info("line %d %s", i, "x" * 40)
    names = sorted(p.name for p in log_dir.iterdir())
    assert names == [LOG_NAME, f"{LOG_NAME}.1", f"{LOG_NAME}.2"]  # older ones dropped


def test_other_libraries_stay_out(log_dir: Path) -> None:
    logging.getLogger("httpx").warning("noise from a library")
    assert "noise" not in (log_dir / LOG_NAME).read_text(encoding="utf-8")


def test_export_diagnostics(log_dir: Path, tmp_path: Path) -> None:
    logging.getLogger("opendm.test").error("failed: %s", SECRET_URL)
    settings = {
        "download_dir": "D:\\Downloads", "proxy_url": "http://user:SECRETPW@proxy.lan:8080",
        "connections": 8,
    }  # fmt: skip
    target = export_diagnostics(
        tmp_path / "out" / "diag.zip", log_dir=log_dir, settings=settings,
        about={"version": "1.0.0", "tools": {"yt-dlp": "2026.10.26"}},
    )  # fmt: skip
    with zipfile.ZipFile(target) as z:
        names = set(z.namelist())
        assert {"about.json", "settings.json", f"logs/{LOG_NAME}"} <= names
        everything = "".join(z.read(n).decode("utf-8") for n in names)
        stored = json.loads(z.read("settings.json"))
        about = json.loads(z.read("about.json"))
    assert "SECRET" not in everything
    assert stored["connections"] == 8 and "proxy.lan" in stored["proxy_url"]
    assert about["version"] == "1.0.0" and "windows" in about and "python" in about


def test_export_without_logs(tmp_path: Path) -> None:
    target = export_diagnostics(
        tmp_path / "diag.zip", log_dir=tmp_path / "none", settings={}, about={}
    )
    with zipfile.ZipFile(target) as z:
        assert set(z.namelist()) == {"about.json", "settings.json"}
