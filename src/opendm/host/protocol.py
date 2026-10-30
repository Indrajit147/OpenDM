"""Native Messaging wire format and browser-message validation (spec 6.6).

Chrome/Edge send a 32-bit little-endian length and UTF-8 JSON on stdin; replies use the
same framing on stdout and may be at most 1 MB. Browser messages are translated into IPC
requests and validated with the IPC protocol's strict schemas before anything is sent.
"""

import json
import struct
from typing import Any, BinaryIO

from opendm.ipc.protocol import ProtocolError, decode_request, encode_request

MAX_FROM_BROWSER = 4 * 1024 * 1024  # Chrome allows more; nothing we need comes close
MAX_TO_BROWSER = 1024 * 1024


class BrowserMessageError(Exception):
    """A malformed or disallowed message from the browser."""


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """One framed message, or None at end of input."""
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise BrowserMessageError("truncated length")
    (length,) = struct.unpack("<I", header)
    if length > MAX_FROM_BROWSER:
        raise BrowserMessageError("message too large")
    body = stream.read(length)
    if len(body) < length:
        raise BrowserMessageError("truncated message")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BrowserMessageError("message is not valid JSON") from exc
    if not isinstance(message, dict):
        raise BrowserMessageError("message must be a JSON object")
    return message


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_TO_BROWSER:
        raise BrowserMessageError("reply too large")
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()


# Browser (camelCase) field -> IPC argument
_DOWNLOAD_FIELDS = {
    "url": "url", "pageUrl": "page_url", "pageTitle": "page_title", "referrer": "referrer",
    "userAgent": "user_agent", "cookies": "cookies", "filename": "filename",
    "fileSize": "file_size", "media": "media",
}  # fmt: skip
_LINKS_FIELDS = {"urls": "urls", "pageUrl": "page_url", "pageTitle": "page_title",
                 "referrer": "referrer"}  # fmt: skip


def _map(message: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
    unknown = set(message) - set(fields) - {"type"}
    if unknown:
        raise BrowserMessageError(f"unknown field(s): {', '.join(sorted(unknown))}")
    return {fields[k]: v for k, v in message.items() if k != "type" and v is not None}


def translate(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Browser message -> validated (IPC command, arguments)."""
    kind = message.get("type")
    if kind == "status":
        cmd, args = "ping", {}
    elif kind == "download":
        cmd, args = "capture", _map(message, _DOWNLOAD_FIELDS)
    elif kind == "links":
        cmd, args = "capture_links", _map(message, _LINKS_FIELDS)
    else:
        raise BrowserMessageError(f"unknown message type: {kind!r}")
    try:
        request = decode_request(encode_request(cmd, args))
    except ProtocolError as exc:
        raise BrowserMessageError(str(exc)) from exc
    return request.cmd, request.args
