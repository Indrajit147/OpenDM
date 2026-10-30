"""Content-Disposition parsing (RFC 6266 / RFC 5987) and filename selection."""

import pytest

from opendm.engine.http.disposition import parse_content_disposition
from opendm.engine.http.naming import choose_filename, filename_from_url

UTF8_NAME = "রিপোর্ট € file.pdf"


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ('attachment; filename="foo.html"', "foo.html"),
        ("attachment; filename=foo.html", "foo.html"),
        ('inline; filename="foo.pdf"', "foo.pdf"),
        ('attachment; FILENAME="foo.html"', "foo.html"),
        ('attachment; filename = "foo.html"', "foo.html"),
        ('attachment; filename="foo;bar.html"', "foo;bar.html"),
        (r'attachment; filename="f\"oo.html"', 'f"oo.html'),
        (r'attachment; filename="\"quoting\" tested.html"', '"quoting" tested.html'),
        ('filename="foo.html"', "foo.html"),  # missing disposition type
        ("attachment; filename*=UTF-8''%e2%82%ac%20rates", "€ rates"),
        ("attachment; filename*=iso-8859-1'en'%A3%20rates", "£ rates"),
        ("attachment; filename*=UTF-8'en'%e2%82%ac%20rates.txt", "€ rates.txt"),
        # filename* wins whatever the order
        ("attachment; filename=\"EURO rates\"; filename*=utf-8''%e2%82%ac%20rates", "€ rates"),
        ("attachment; filename*=utf-8''%e2%82%ac%20rates; filename=\"EURO rates\"", "€ rates"),
        # broken filename* falls back to filename
        ("attachment; filename*=foo''bar; filename=\"plain.txt\"", "plain.txt"),
        ("attachment; filename*=UTF-8''%FF%FE; filename=\"plain.txt\"", "plain.txt"),
        # already-decoded Unicode passes through
        (f'attachment; filename="{UTF8_NAME}"', UTF8_NAME),
        # raw UTF-8 bytes decoded as Latin-1 by the HTTP layer
        (f'attachment; filename="{UTF8_NAME}"'.encode().decode("latin-1"), UTF8_NAME),
        # genuine Latin-1 name is left alone
        ('attachment; filename="café.txt"', "café.txt"),
        # percent-encoded plain filename (decision M1-6)
        ('attachment; filename="%E2%82%AC%20rates.pdf"', "€ rates.pdf"),
        ('attachment; filename="100% pure.txt"', "100% pure.txt"),
        ('attachment; filename="%FF%FE.bin"', "%FF%FE.bin"),
    ],
)
def test_parse_content_disposition(header: str, name: str) -> None:
    assert parse_content_disposition(header) == name


@pytest.mark.parametrize(
    "header", ["attachment", 'attachment; filename=""', "", "attachment; foo=bar", "  ;;  "]
)
def test_parse_content_disposition_without_name(header: str) -> None:
    assert parse_content_disposition(header) is None


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("http://h/a/b%20c.zip?x=1#f", "b c.zip"),
        ("http://h/a/%E0%A6%B0.pdf", "র.pdf"),
        ("http://h/", None),
        ("http://h", None),
        ("http://h/dir/", None),
    ],
)
def test_filename_from_url(url: str, name: str | None) -> None:
    assert filename_from_url(url) == name


@pytest.mark.parametrize(
    ("cd", "url", "ctype", "name"),
    [
        ('attachment; filename="x.pdf"', "http://h/get?id=1", "application/pdf", "x.pdf"),
        (None, "http://h/get.php?id=1", "application/pdf", "get.pdf"),
        (None, "http://h/view.aspx", "image/png", "view.png"),
        (None, "http://h/get.php?id=1", "application/octet-stream", "get.php"),
        (None, "http://h/", "text/html; charset=utf-8", "download.html"),
        (None, "http://h/", None, "download"),
        (None, "http://h/file", "application/zip", "file.zip"),
        (None, "http://h/file", "application/octet-stream", "file"),
        (None, "http://h/a.tar.gz", "application/gzip", "a.tar.gz"),
        ('attachment; filename="../evil.exe"', "http://h/x", None, "evil.exe"),
        ('attachment; filename="CON.txt"', "http://h/x", None, "CON_.txt"),
        ("attachment", "http://h/report.csv", None, "report.csv"),
    ],
)
def test_choose_filename(cd: str | None, url: str, ctype: str | None, name: str) -> None:
    assert choose_filename(cd, url, ctype) == name
