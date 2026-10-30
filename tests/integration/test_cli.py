"""opendm-cli, run in-process against the local test server."""

import hashlib
from pathlib import Path
from urllib.parse import quote

import pytest

from opendm.cli.__main__ import main, parse_header
from tests.server.app import FaultServer, content_sha256

SIZE = 200_000


def test_get_standalone(server: FaultServer, tmp_path: Path, capsys) -> None:
    url = server.url(f"/file/a.bin?size={SIZE}")
    assert main(["get", url, "-o", str(tmp_path), "--standalone"]) == 0
    target = tmp_path / "a.bin"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == content_sha256(SIZE, 1)
    out = capsys.readouterr().out
    assert str(target) in out
    assert content_sha256(SIZE, 1) in out


def test_get_utf8_name(server: FaultServer, tmp_path: Path, capsys) -> None:
    name = "রিপোর্ট € file.pdf"
    url = server.url(f"/file/x.bin?size=100&cd={quote(name)}")
    assert main(["get", url, "-o", str(tmp_path), "--standalone"]) == 0
    assert (tmp_path / name).exists()


def test_get_with_name_header_and_connections(server: FaultServer, tmp_path: Path, capsys) -> None:
    url = server.url("/protected/p.bin?size=100")
    code = main(
        [
            "get", url, "-o", str(tmp_path), "--standalone", "-n", "renamed.bin", "-c", "4",
            "--header", "Cookie: odm_session=opendm-test", "--user-agent", "Test/1",
            "--referer", "http://example.com/",
        ]
    )  # fmt: skip
    assert code == 0
    assert (tmp_path / "renamed.bin").stat().st_size == 100
    assert "multi-connection" in capsys.readouterr().err


def test_get_default_folder_is_cwd(server: FaultServer, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["get", server.url("/file/a.bin?size=10"), "--standalone", "-q"]) == 0
    assert (tmp_path / "a.bin").exists()


def test_get_http_error(server: FaultServer, tmp_path: Path, capsys) -> None:
    assert main(["get", server.url("/status/404"), "-o", str(tmp_path), "--standalone"]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "404" in err


def test_get_failure_reports_partial(server: FaultServer, tmp_path: Path, capsys) -> None:
    url = server.url(f"/file/a.bin?size={SIZE}&drop_at=5000")
    assert main(["get", url, "-o", str(tmp_path), "--standalone"]) == 1
    assert "partial file kept" in capsys.readouterr().err


def test_get_bad_url_is_usage_error(tmp_path: Path, capsys) -> None:
    assert main(["get", "ftp://example.com/a.zip", "-o", str(tmp_path), "--standalone"]) == 2
    assert "unsupported URL scheme" in capsys.readouterr().err


def test_get_requires_standalone_until_ipc_exists(server: FaultServer, capsys) -> None:
    assert main(["get", server.url("/file/a.bin?size=10")]) == 2
    assert "--standalone" in capsys.readouterr().err


@pytest.mark.parametrize("command", [["list"], ["pause", "1"], ["resume", "1"], ["remove", "1"]])
def test_app_commands_not_available_yet(command: list[str], capsys) -> None:
    assert main(command) == 2
    assert "running OpenDM app" in capsys.readouterr().err


def test_bad_header_is_usage_error(server: FaultServer, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["get", server.url("/x"), "--standalone", "--header", "no-colon"])
    assert exc.value.code == 2


def test_parse_header() -> None:
    assert parse_header("X-Token:  abc ") == ("X-Token", "abc")
    with pytest.raises(ValueError):
        parse_header(": value")


def test_no_command_shows_help(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
