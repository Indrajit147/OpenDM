"""Log files and the diagnostics ZIP (spec 6.11, decision D67).

Logs rotate (5 x 1 MB by default) in ``<data folder>\\logs``. Every message passes through
``redact_text`` before it is written: link query strings, user names/passwords in links,
cookies and authorization values are removed. Only OpenDM's own loggers ("opendm.*") write
there. Nothing is ever sent anywhere; "Export diagnostics" saves a ZIP the user can attach.
"""

import json
import logging
import logging.handlers
import platform
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

from opendm.core.redact import REDACTED, redact_url

LOG_NAME = "opendm.log"
_ROOT = "opendm"
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)
_SECRET_FIELD = re.compile(
    r"\b(cookie|set-cookie|authorization|proxy-authorization)(\s*[:=]\s*)[^\r\n]*",
    re.IGNORECASE,
)
_handler: logging.Handler | None = None


def redact_text(text: str) -> str:
    def url(match: re.Match[str]) -> str:
        value = match.group(0)
        trailing = ""
        while value and value[-1] in ".,;)]":
            value, trailing = value[:-1], value[-1] + trailing
        return redact_url(value) + trailing

    text = _SECRET_FIELD.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return _URL.sub(url, text)


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def setup_logging(folder: Path | None, *, max_bytes: int = 1024 * 1024, backups: int = 4) -> None:
    """Send "opendm.*" logs to ``folder/opendm.log`` (None: stop writing a file)."""
    global _handler
    root = logging.getLogger(_ROOT)
    if _handler is not None:
        root.removeHandler(_handler)
        _handler.close()
        _handler = None
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        folder / LOG_NAME, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(_RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    _handler = handler


def export_diagnostics(
    target: Path, *, log_dir: Path, settings: dict[str, Any], about: dict[str, Any]
) -> Path:
    """Write a ZIP with the logs, the settings and version information; secrets removed."""
    if _handler is not None:
        _handler.flush()
    info = {
        **about,
        "windows": platform.platform(),
        "python": sys.version.split()[0],
    }
    clean_settings = {
        key: redact_text(value) if isinstance(value, str) else value
        for key, value in settings.items()
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.json", json.dumps(info, indent=2, default=str))
        z.writestr("settings.json", json.dumps(clean_settings, indent=2, default=str))
        if log_dir.is_dir():
            for path in sorted(log_dir.glob(LOG_NAME + "*")):
                text = path.read_text(encoding="utf-8", errors="replace")
                z.writestr(f"logs/{path.name}", redact_text(text))  # older logs, once more
    return target
