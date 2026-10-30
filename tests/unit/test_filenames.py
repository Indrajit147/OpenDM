from pathlib import Path

import pytest

from opendm.core.branding import PARTIAL_SUFFIX
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.filenames import (
    DEFAULT_NAME,
    fit_to_path,
    sanitize_filename,
    split_ext,
    unique_path,
    utf16_len,
)
from opendm.discovery.content_types import extension_for, parse_content_type


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("report.pdf", "report.pdf"),
        ("রিপোর্ট € file.pdf", "রিপোর্ট € file.pdf"),
        ('a<b>c:d"e|f?g*h.txt', "a_b_c_d_e_f_g_h.txt"),
        ("tab\there\x00.txt", "tab_here_.txt"),
        ("name. . .", "name"),
        ("  name.txt  ", "name.txt"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\Windows\\win.ini", "win.ini"),
        ("C:\\temp\\x.bin", "x.bin"),
        ("dir/", "dir"),
        ("CON", "CON_"),
        ("con.txt", "con_.txt"),
        ("NUL.tar.gz", "NUL_.tar.gz"),
        ("com1.log", "com1_.log"),
        ("LPT9", "LPT9_"),
        ("COM¹.txt", "COM¹_.txt"),
        ("console.txt", "console.txt"),
        ("", DEFAULT_NAME),
        (".", DEFAULT_NAME),
        ("..", DEFAULT_NAME),
        ("...", DEFAULT_NAME),
        (".bashrc", ".bashrc"),
    ],
)
def test_sanitize_filename(raw: str, clean: str) -> None:
    assert sanitize_filename(raw) == clean


def test_sanitize_uses_given_default() -> None:
    assert sanitize_filename("///", default="") == ""


def test_sanitize_truncates_long_names_keeping_extension() -> None:
    name = "a" * 300 + ".zip"
    clean = sanitize_filename(name)
    assert utf16_len(clean) == 255
    assert clean.endswith(".zip")


def test_sanitize_counts_utf16_units() -> None:
    clean = sanitize_filename("😀" * 200 + ".txt")  # each emoji is 2 UTF-16 units
    assert utf16_len(clean) <= 255
    assert clean.endswith(".txt")


@pytest.mark.parametrize(
    ("name", "parts"),
    [
        ("a.zip", ("a", ".zip")),
        ("a.tar.gz", ("a.tar", ".gz")),
        ("noext", ("noext", "")),
        (".bashrc", (".bashrc", "")),
        ("odd.my document", ("odd.my document", "")),
    ],
)
def test_split_ext(name: str, parts: tuple[str, str]) -> None:
    assert split_ext(name) == parts


def test_unique_path(tmp_path: Path) -> None:
    assert unique_path(tmp_path, "a.zip") == tmp_path / "a.zip"
    (tmp_path / "a.zip").write_text("")
    assert unique_path(tmp_path, "a.zip") == tmp_path / "a (1).zip"
    (tmp_path / ("a (1).zip" + PARTIAL_SUFFIX)).write_text("")  # in-progress download
    assert unique_path(tmp_path, "a.zip") == tmp_path / "a (2).zip"


def test_fit_to_path_leaves_short_names(tmp_path: Path) -> None:
    assert fit_to_path(tmp_path, "a.zip", limit=259) == "a.zip"


def test_fit_to_path_shortens_stem(tmp_path: Path) -> None:
    limit = len(str(tmp_path)) + 1 + 30
    name = fit_to_path(tmp_path, "x" * 100 + ".zip", limit=limit)
    assert name.endswith(".zip")
    assert len(str(tmp_path / (name + PARTIAL_SUFFIX))) <= limit


def test_fit_to_path_impossible(tmp_path: Path) -> None:
    with pytest.raises(DownloadError) as exc:
        fit_to_path(tmp_path, "file.zip", limit=len(str(tmp_path)) + 5)
    assert exc.value.kind is ErrorKind.PATH_TOO_LONG


# --- content types -------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "mime"),
    [
        ("application/PDF", "application/pdf"),
        ("text/html; charset=utf-8", "text/html"),
        ("  video/mp4 ", "video/mp4"),
        ("", ""),
        (None, ""),
    ],
)
def test_parse_content_type(header: str | None, mime: str) -> None:
    assert parse_content_type(header) == mime


@pytest.mark.parametrize(
    ("header", "ext"),
    [
        ("application/pdf", ".pdf"),
        ("video/mp4; codecs=avc1", ".mp4"),
        ("application/x-zip-compressed", ".zip"),
        ("application/vnd.apple.mpegurl", ".m3u8"),
        ("application/octet-stream", ""),
        ("application/x-unknown-thing", ""),
        (None, ""),
    ],
)
def test_extension_for(header: str | None, ext: str) -> None:
    assert extension_for(header) == ext
