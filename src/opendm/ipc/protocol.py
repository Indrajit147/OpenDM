"""IPC wire format: one JSON object per line, UTF-8, at most 1 MiB (spec 7: validate all).

Request:  {"v": 1, "cmd": "<command>", "args": {...}}
Response: {"v": 1, "ok": true, "result": ...} | {"v": 1, "ok": false, "error": "..."}
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from opendm.core.branding import PIPE_NAME
from opendm.core.errors import DownloadError
from opendm.engine.http.transport import validate_url
from opendm.engine.media.formats import MediaOptions

VERSION = 1
MAX_MESSAGE = 1024 * 1024
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class ProtocolError(Exception):
    """A malformed or disallowed message."""


@dataclass(frozen=True)
class Request:
    cmd: str
    args: dict[str, Any] = field(default_factory=dict)


def pipe_name(user: str) -> str:
    """Per-user pipe name (the server additionally restricts access to that user)."""
    safe = re.sub(r"[^a-z0-9_]+", "_", user.lower()).strip("_") or "user"
    return f"{PIPE_NAME}-{safe}"


# --- argument checks ------------------------------------------------------------------------


def _url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ProtocolError("url must be a string")
    try:
        validate_url(value)
    except DownloadError as exc:
        raise ProtocolError(f"bad url: {exc.message} (only http/https scheme allowed)") from exc
    return value


def _str(limit: int = 4096) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if not isinstance(value, str) or len(value) > limit or "\x00" in value:
            raise ProtocolError("expected a string")
        return value

    return check


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError("expected true or false")
    return value


def _int(low: int, high: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ProtocolError(f"expected an integer {low}-{high}")
        return value

    return check


def _headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 64:
        raise ProtocolError("headers must be an object")
    for name, val in value.items():
        if not (isinstance(name, str) and _HEADER_NAME.match(name)):
            raise ProtocolError("headers: invalid name")
        if not isinstance(val, str) or "\r" in val or "\n" in val or len(val) > 16384:
            raise ProtocolError("headers: invalid value")
    return value


def _urls(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 1000:
        raise ProtocolError("urls must be a list")
    return [_url(u) for u in value]


_MEDIA_KEYS = frozenset({"quality", "container", "subtitles", "auto_subtitles", "embed_thumbnail"})


def _media(value: Any) -> dict[str, Any]:
    """yt-dlp options for a media download (validated by MediaOptions)."""
    if not isinstance(value, dict) or set(value) - _MEDIA_KEYS:
        raise ProtocolError(f"media must be an object with keys {sorted(_MEDIA_KEYS)}")
    subtitles = value.get("subtitles", [])
    if not isinstance(subtitles, list) or len(subtitles) > 50:
        raise ProtocolError("media.subtitles must be a list")
    try:
        return MediaOptions.from_dict(value).to_dict()
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"media: {exc}") from None


_ARGS: dict[str, dict[str, Callable[[Any], Any]]] = {
    "ping": {},
    "list": {},
    "add": {
        "url": _url,
        "dest_dir": _str(),
        "filename": _str(255),
        "start": _bool,
        "queue_id": _int(1, 2**31),
        "connections": _int(1, 32),
        "speed_limit": _int(0, 2**40),
        "checksum": _str(200),
        "referrer": _str(8192),
        "user_agent": _str(1024),
        "cookies": _str(65536),
        "headers": _headers,
        "media": _media,
    },
    "pause": {"job_id": _str(64)},
    "resume": {"job_id": _str(64)},
    "remove": {"job_id": _str(64), "delete_file": _bool},
    "activate": {"urls": _urls},
}
_REQUIRED = {"add": {"url"}, "pause": {"job_id"}, "resume": {"job_id"}, "remove": {"job_id"}}


def decode_request(data: bytes) -> Request:
    if len(data) > MAX_MESSAGE:
        raise ProtocolError("message too large")
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("message is not valid JSON") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("message must be a JSON object")
    if obj.get("v") != VERSION:
        raise ProtocolError("unsupported protocol version")
    cmd = obj.get("cmd")
    if cmd not in _ARGS:
        raise ProtocolError(f"unknown command: {cmd!r}")
    args = obj.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("args must be an object")
    schema = _ARGS[cmd]
    unknown = set(args) - set(schema)
    if unknown:
        raise ProtocolError(f"unknown argument(s): {', '.join(sorted(unknown))}")
    missing = _REQUIRED.get(cmd, set()) - set(args)
    if missing:
        raise ProtocolError(f"missing argument(s): {', '.join(sorted(missing))}")
    checked = {}
    for name, value in args.items():
        try:
            checked[name] = schema[name](value)
        except ProtocolError as exc:
            raise ProtocolError(f"{name}: {exc}") from None
    return Request(cmd, checked)


def encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"


def encode_request(cmd: str, args: dict[str, Any] | None = None) -> bytes:
    return encode({"v": VERSION, "cmd": cmd, "args": args or {}})


def ok_response(result: Any) -> dict[str, Any]:
    return {"v": VERSION, "ok": True, "result": result}


def error_response(message: str) -> dict[str, Any]:
    return {"v": VERSION, "ok": False, "error": message}
