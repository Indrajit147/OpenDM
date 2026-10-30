"""opendm-cli, run in-process against the local test server."""

import hashlib
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from opendm.cli.__main__ import main, parse_header
from opendm.engine.http.resume import load_state
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


def test_get_default_folder_is_cwd(server: FaultServer, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["get", server.url("/file/a.bin?size=10"), "--standalone", "-q"]) == 0
    assert (tmp_path / "a.bin").exists()


def test_get_http_error(server: FaultServer, tmp_path: Path, capsys) -> None:
    assert main(["get", server.url("/status/404"), "-o", str(tmp_path), "--standalone"]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "404" in err


def test_get_failure_reports_partial(server: FaultServer, tmp_path: Path, capsys) -> None:
    # The GET drops at byte 5000; its retry then finds the file changed (not retryable).
    url = server.url(f"/file/a.bin?size={SIZE}&drop_at=5000&etag_after=2")
    assert main(["get", url, "-o", str(tmp_path), "--standalone", "-c", "1"]) == 1
    err = capsys.readouterr().err
    assert "partial file kept" in err and "a.bin.odm-part" in err


def test_get_bad_url_is_usage_error(tmp_path: Path, capsys) -> None:
    assert main(["get", "ftp://example.com/a.zip", "-o", str(tmp_path), "--standalone"]) == 2
    assert "unsupported URL scheme" in capsys.readouterr().err


def test_get_without_app_suggests_standalone(server: FaultServer, capsys) -> None:
    assert main(["get", server.url("/file/a.bin?size=10")]) == 1
    err = capsys.readouterr().err
    assert "not running" in err and "--standalone" in err


@pytest.mark.parametrize("command", [["list"], ["pause", "1"], ["resume", "1"], ["remove", "1"]])
def test_app_commands_without_app(command: list[str], capsys) -> None:
    assert main(command) == 1
    assert "not running" in capsys.readouterr().err


@pytest.mark.parametrize("flag", [["--restart"], ["--insecure"], ["--continue", "x.odm-part"]])
def test_standalone_only_flags(server: FaultServer, flag: list[str], capsys) -> None:
    assert main(["get", server.url("/file/a.bin?size=10"), *flag]) == 2
    assert "only work with --standalone" in capsys.readouterr().err


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


# --- M2 options -------------------------------------------------------------------------------


def test_checksum_option(server: FaultServer, tmp_path: Path, capsys) -> None:
    url = server.url(f"/file/a.bin?size={SIZE}")
    good = content_sha256(SIZE, 1)
    assert main(["get", url, "-o", str(tmp_path), "--standalone", "--sha256", good]) == 0
    bad = "0" * 32
    assert main(["get", url, "-o", str(tmp_path), "--standalone", "--md5", bad]) == 1
    assert "checksum_mismatch" in capsys.readouterr().err


def test_malformed_checksum_is_usage_error(server: FaultServer, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["get", server.url("/x"), "--standalone", "--sha256", "abc"])
    assert exc.value.code == 2


@pytest.mark.parametrize("args", [["-c", "0"], ["-c", "33"], ["--limit", "fast"]])
def test_bad_option_values(server: FaultServer, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["get", server.url("/x"), "--standalone", *args])
    assert exc.value.code == 2


def test_limit_option(server: FaultServer, tmp_path: Path) -> None:
    url = server.url("/file/a.bin?size=1M")
    t0 = time.perf_counter()
    assert main(["get", url, "-o", str(tmp_path), "--standalone", "--limit", "1M"]) == 0
    assert time.perf_counter() - t0 >= 0.85


def test_validator_change_suggests_restart(server: FaultServer, tmp_path: Path, capsys) -> None:
    path = "/file/a.bin?size=1M&etag_after=1"  # the HEAD sees v0, every GET sees v1
    args = ["get", server.url(path), "-o", str(tmp_path), "--standalone", "-q"]
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "validator_changed" in err and "--restart" in err


# --- the M2 acceptance test: hard kill, then resume -------------------------------------------


def test_kill_and_resume_gives_correct_sha256(server: FaultServer, tmp_path: Path) -> None:
    size = 100 * 1024 * 1024
    path = "/file/big.bin?size=100M&seed=3&rate=2M"  # 8 x 2 MiB/s: about 6 s in total
    cmd = [
        sys.executable, "-m", "opendm.cli", "get", server.url(path),
        "-o", str(tmp_path), "--standalone", "-c", "8", "-q",
    ]  # fmt: skip
    state_file = tmp_path / "big.bin.odm-state"

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = load_state(state_file)
            if state is not None and state.written >= 16 * 1024 * 1024:
                break
            time.sleep(0.05)
        else:
            pytest.fail("no checkpoint with progress appeared")
        proc.kill()  # TerminateProcess: no cleanup code runs
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()

    state = load_state(state_file)
    assert state is not None and (tmp_path / "big.bin.odm-part").exists()
    sent_before = server.stats(path)["bytes_sent"]

    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    target = tmp_path / "big.bin"
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    assert digest == content_sha256(size, 3)
    resumed = server.stats(path)["bytes_sent"] - sent_before
    missing = size - state.written
    assert missing <= resumed <= missing + 4 * 1024 * 1024  # splits may overshoot a little
    assert sorted(p.name for p in tmp_path.iterdir()) == ["big.bin"]


# --- M5: --media --------------------------------------------------------------------------------

FAKE_YTDLP = Path(__file__).resolve().parents[1] / "fake_tools" / "fake_ytdlp.py"


def test_media_standalone(tmp_path: Path, monkeypatch, capsys) -> None:
    from opendm.cli import __main__ as cli
    from opendm.engine.media.ytdlp import ToolPaths

    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"")
    fake = ToolPaths(ffmpeg=ffmpeg, command=(sys.executable, str(FAKE_YTDLP)))
    monkeypatch.setattr(cli, "media_tools", lambda folder: fake)
    code = main(["get", "http://fake/ok", "--media", "--quality", "mp3", "-o", str(tmp_path / "dl"),
                 "--standalone"])  # fmt: skip
    assert code == 0
    assert (tmp_path / "dl" / "Fake Clip [abc].mp3").exists()
    assert "Saved:" in capsys.readouterr().out


def test_media_without_tools_explains(tmp_path: Path, capsys) -> None:
    code = main(["get", "http://fake/ok", "--media", "--tools-dir", str(tmp_path / "none"),
                 "-o", str(tmp_path), "--standalone"])  # fmt: skip
    assert code == 1
    assert "tool_missing" in capsys.readouterr().err


def test_media_rejects_http_only_options(capsys) -> None:
    assert main(["get", "http://fake/ok", "--media", "--restart", "--standalone"]) == 2
    with pytest.raises(SystemExit):
        main(["get", "http://fake/ok", "--media", "--quality", "8k", "--standalone"])
