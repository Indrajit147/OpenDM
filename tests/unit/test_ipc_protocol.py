"""IPC message validation (no Qt)."""

import json

import pytest

from opendm.ipc.protocol import (
    MAX_MESSAGE,
    ProtocolError,
    decode_request,
    encode,
    error_response,
    ok_response,
    pipe_name,
)


def line(obj: object) -> bytes:
    return json.dumps(obj).encode() + b"\n"


def test_add_request() -> None:
    req = decode_request(
        line(
            {
                "v": 1,
                "cmd": "add",
                "args": {
                    "url": "https://example.com/a.zip",
                    "dest_dir": "D:/dl",
                    "start": False,
                    "connections": 4,
                    "headers": {"X-A": "1"},
                    "cookies": "a=b",
                    "speed_limit": 1000,
                    "checksum": "md5:" + "0" * 32,
                    "filename": "a.zip",
                    "referrer": "https://example.com/",
                    "user_agent": "UA",
                    "queue_id": 2,
                },
            }
        )
    )
    assert req.cmd == "add"
    assert req.args["url"] == "https://example.com/a.zip"
    assert req.args["start"] is False


@pytest.mark.parametrize(
    "obj",
    [
        {"v": 1, "cmd": "list"},
        {"v": 1, "cmd": "ping", "args": {}},
        {"v": 1, "cmd": "pause", "args": {"job_id": "abc123"}},
        {"v": 1, "cmd": "remove", "args": {"job_id": "abc123", "delete_file": True}},
        {"v": 1, "cmd": "activate", "args": {"urls": ["http://h/a", "https://h/b"]}},
    ],
)
def test_valid_requests(obj: dict) -> None:
    assert decode_request(line(obj)).cmd == obj["cmd"]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"not json\n", "JSON"),
        (b"[]\n", "object"),
        (line({"cmd": "list"}), "version"),
        (line({"v": 2, "cmd": "list"}), "version"),
        (line({"v": 1, "cmd": "format_disk"}), "unknown command"),
        (line({"v": 1, "cmd": "add", "args": {}}), "url"),
        (line({"v": 1, "cmd": "add", "args": {"url": "file:///C:/x"}}), "scheme"),
        (line({"v": 1, "cmd": "add", "args": {"url": "javascript:alert(1)"}}), "scheme"),
        (line({"v": 1, "cmd": "add", "args": {"url": "http://h/a", "evil": 1}}), "unknown"),
        (line({"v": 1, "cmd": "add", "args": {"url": "http://h/a", "connections": 99}}), "1-32"),
        (line({"v": 1, "cmd": "add", "args": {"url": "http://h/a", "start": "yes"}}), "start"),
        (
            line({"v": 1, "cmd": "add", "args": {"url": "http://h/a", "headers": {"a": 1}}}),
            "headers",
        ),
        (
            line({"v": 1, "cmd": "add", "args": {"url": "http://h/a", "headers": {"A\r\nB": "x"}}}),
            "headers",
        ),
        (line({"v": 1, "cmd": "pause", "args": {}}), "job_id"),
        (line({"v": 1, "cmd": "activate", "args": {"urls": ["ftp://x"]}}), "scheme"),
        (b"{" + b" " * MAX_MESSAGE + b"}\n", "too large"),
    ],
)
def test_invalid_requests(data: bytes, reason: str) -> None:
    with pytest.raises(ProtocolError, match=reason):
        decode_request(data)


def test_responses_round_trip() -> None:
    assert json.loads(encode(ok_response({"n": 1}))) == {"v": 1, "ok": True, "result": {"n": 1}}
    assert json.loads(encode(error_response("nope"))) == {"v": 1, "ok": False, "error": "nope"}
    assert encode(ok_response(None)).endswith(b"\n")


def test_pipe_name_is_per_user() -> None:
    assert pipe_name("Indrajit Gupta") == "opendm-ipc-indrajit_gupta"
    assert pipe_name("..\\evil/") == "opendm-ipc-evil"


def test_media_argument() -> None:
    req = decode_request(line({"v": 1, "cmd": "add", "args": {
        "url": "https://example.com/watch?v=1", "media": {"quality": "720", "subtitles": ["en"]},
    }}))  # fmt: skip
    assert req.args["media"]["quality"] == "720"
    assert req.args["media"]["subtitles"] == ["en"]


@pytest.mark.parametrize(
    "media",
    [
        {"quality": "8k"},
        {"container": "avi"},
        {"subtitles": ["en;rm -rf"]},
        {"subtitles": "en"},
        {"quality": "best", "cookies_from_browser": "chrome"},
        "best",
    ],
)
def test_media_argument_rejects(media: object) -> None:
    with pytest.raises(ProtocolError, match="media"):
        decode_request(line({"v": 1, "cmd": "add", "args": {"url": "https://h/x", "media": media}}))
