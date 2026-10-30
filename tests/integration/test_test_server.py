"""Every fault case of the local test server, exercised with stdlib http.client."""

import gzip
import hashlib
import http.client
import time
from urllib.parse import quote

import pytest

from tests.server.app import (
    COOKIE_NAME,
    COOKIE_VALUE,
    FaultServer,
    RangeNotSatisfiable,
    content_bytes,
    content_seed,
    content_sha256,
    parse_range,
    parse_size,
)

SIZE = 200_000  # spans several 64 KiB generator chunks


def request(
    server: FaultServer, path: str, method: str = "GET", headers: dict[str, str] | None = None
) -> tuple[http.client.HTTPResponse, bytes]:
    conn = http.client.HTTPConnection(server.host, server.port, timeout=10)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        return resp, resp.read()
    finally:
        conn.close()


# --- deterministic content -------------------------------------------------


def test_content_is_deterministic_and_seeded() -> None:
    a = content_bytes(SIZE, seed=1)
    assert len(a) == SIZE
    assert a == content_bytes(SIZE, seed=1)
    assert a != content_bytes(SIZE, seed=2)


def test_content_slices_match_full_content_across_chunk_boundaries() -> None:
    full = content_bytes(SIZE, seed=7)
    for start, end in [(0, 1), (65_530, 65_545), (131_071, 131_073), (SIZE - 5, SIZE)]:
        assert content_bytes(SIZE, 7, start, end) == full[start:end]


def test_content_sha256_matches_bytes() -> None:
    assert content_sha256(SIZE, 3) == hashlib.sha256(content_bytes(SIZE, 3)).hexdigest()


@pytest.mark.parametrize(
    ("text", "expected"),
    [("123", 123), ("4K", 4096), ("2M", 2 * 1024**2), ("1G", 1024**3), ("10k", 10_240)],
)
def test_parse_size(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-99", (0, 100)),
        ("bytes=100-", (100, 1000)),
        ("bytes=-100", (900, 1000)),
        ("bytes=-5000", (0, 1000)),
        ("bytes=990-5000", (990, 1000)),
        ("bytes=0-0", (0, 1)),
        ("items=0-1", None),  # unknown unit: ignore Range
        ("bytes=0-1,5-9", None),  # multi-range: serve full body
        ("bytes=9-3", None),  # invalid: ignore Range
        ("bytes=abc", None),
    ],
)
def test_parse_range(header: str, expected: tuple[int, int] | None) -> None:
    assert parse_range(header, 1000) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=5000-6000", "bytes=-0"])
def test_parse_range_unsatisfiable(header: str) -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 1000)


# --- range supported (the normal case) ---------------------------------------


def test_full_get(server: FaultServer) -> None:
    resp, body = request(server, f"/file/a.bin?size={SIZE}&seed=5")
    assert resp.status == 200
    assert resp.getheader("Content-Length") == str(SIZE)
    assert resp.getheader("Accept-Ranges") == "bytes"
    assert resp.getheader("ETag")
    assert resp.getheader("Last-Modified")
    assert hashlib.sha256(body).hexdigest() == content_sha256(SIZE, 5)


def test_head_has_headers_but_no_body(server: FaultServer) -> None:
    resp, body = request(server, f"/file/a.bin?size={SIZE}", method="HEAD")
    assert resp.status == 200
    assert resp.getheader("Content-Length") == str(SIZE)
    assert resp.getheader("Accept-Ranges") == "bytes"
    assert body == b""


@pytest.mark.parametrize(
    ("range_header", "start", "end"),
    [
        ("bytes=100-199", 100, 200),
        ("bytes=150000-", 150_000, SIZE),
        ("bytes=-1000", SIZE - 1000, SIZE),
    ],
)
def test_range_request(server: FaultServer, range_header: str, start: int, end: int) -> None:
    resp, body = request(server, f"/file/a.bin?size={SIZE}", headers={"Range": range_header})
    assert resp.status == 206
    assert resp.getheader("Content-Range") == f"bytes {start}-{end - 1}/{SIZE}"
    assert body == content_bytes(SIZE, 1, start, end)


def test_range_not_satisfiable(server: FaultServer) -> None:
    resp, _ = request(server, f"/file/a.bin?size={SIZE}", headers={"Range": f"bytes={SIZE}-"})
    assert resp.status == 416
    assert resp.getheader("Content-Range") == f"bytes */{SIZE}"


def test_content_type_parameter(server: FaultServer) -> None:
    resp, _ = request(server, "/file/v.mp4?size=10&type=video/mp4")
    assert resp.getheader("Content-Type") == "video/mp4"


# --- range unsupported / 200 instead of 206 ----------------------------------


def test_range_unsupported(server: FaultServer) -> None:
    resp, body = request(
        server, f"/file/a.bin?size={SIZE}&range=none", headers={"Range": "bytes=0-9"}
    )
    assert resp.status == 200
    assert resp.getheader("Accept-Ranges") is None
    assert len(body) == SIZE


def test_200_instead_of_206(server: FaultServer) -> None:
    path = f"/file/a.bin?size={SIZE}&range=ignore"
    head, _ = request(server, path, method="HEAD")
    assert head.getheader("Accept-Ranges") == "bytes"  # advertises ranges...
    resp, body = request(server, path, headers={"Range": "bytes=0-9"})
    assert resp.status == 200  # ...but ignores them
    assert resp.getheader("Content-Range") is None
    assert body == content_bytes(SIZE, 1)


# --- no Content-Length ---------------------------------------------------------


def test_no_content_length_close_delimited(server: FaultServer) -> None:
    resp, body = request(server, f"/file/a.bin?size={SIZE}&length=none")
    assert resp.status == 200
    assert resp.getheader("Content-Length") is None
    assert resp.getheader("Transfer-Encoding") is None
    assert body == content_bytes(SIZE, 1)


def test_no_content_length_chunked(server: FaultServer) -> None:
    resp, body = request(server, f"/file/a.bin?size={SIZE}&length=chunked")
    assert resp.getheader("Content-Length") is None
    assert resp.getheader("Transfer-Encoding") == "chunked"
    assert body == content_bytes(SIZE, 1)


# --- Content-Disposition ----------------------------------------------------------

UTF8_NAME = "রিপোর্ট € file.pdf"


def _cd(server: FaultServer, name: str, mode: str) -> str:
    resp, _ = request(server, f"/file/x.bin?size=10&cd={quote(name)}&cd_mode={mode}")
    value = resp.getheader("Content-Disposition")
    assert value is not None
    return value


def test_content_disposition_plain(server: FaultServer) -> None:
    assert _cd(server, "report 1.pdf", "plain") == 'attachment; filename="report 1.pdf"'


def test_content_disposition_ext_value(server: FaultServer) -> None:
    value = _cd(server, UTF8_NAME, "ext")
    assert value == f"attachment; filename*=UTF-8''{quote(UTF8_NAME, safe='')}"


def test_content_disposition_both(server: FaultServer) -> None:
    value = _cd(server, UTF8_NAME, "both")
    assert value.startswith('attachment; filename="')
    assert f"filename*=UTF-8''{quote(UTF8_NAME, safe='')}" in value
    fallback = value.split('filename="')[1].split('"')[0]
    assert fallback.isascii()


def test_content_disposition_raw_utf8(server: FaultServer) -> None:
    # Misbehaving servers send raw UTF-8 bytes; http.client decodes headers as Latin-1.
    raw = _cd(server, UTF8_NAME, "raw").encode("latin-1").decode("utf-8")
    assert raw == f'attachment; filename="{UTF8_NAME}"'


# --- redirects ------------------------------------------------------------------


def test_redirect_chain(server: FaultServer) -> None:
    path = "/redirect/3?to=" + quote("/file/r.bin?size=10", safe="")
    hops = 0
    while True:
        resp, _ = request(server, path)
        if resp.status != 302:
            break
        hops += 1
        path = resp.getheader("Location")
        assert path
    assert hops == 3
    assert resp.status == 200
    assert resp.getheader("Content-Length") == "10"


def test_redirect_status_code(server: FaultServer) -> None:
    resp, _ = request(server, "/redirect/1?code=307")
    assert resp.status == 307
    assert resp.getheader("Location", "").startswith("/file/")


# --- throttling and slow start -------------------------------------------------------


def test_throttle(server: FaultServer) -> None:
    t0 = time.monotonic()
    _, body = request(server, "/file/a.bin?size=100000&rate=200000")
    elapsed = time.monotonic() - t0
    assert len(body) == 100_000
    assert elapsed >= 0.4  # 100 kB at 200 kB/s = 0.5 s


def test_slow_start(server: FaultServer) -> None:
    t0 = time.monotonic()
    resp, _ = request(server, "/file/a.bin?size=10&slow_start=0.3")
    assert resp.status == 200
    assert time.monotonic() - t0 >= 0.3


# --- connection drop at byte N ----------------------------------------------------------


def test_drop_at_byte_then_resume(server: FaultServer) -> None:
    path = f"/file/a.bin?size={SIZE}&drop_at=70000"
    with pytest.raises(http.client.IncompleteRead) as exc:
        request(server, path)
    partial = exc.value.partial
    assert len(partial) == 70_000
    # Resuming from the drop point does not cross it again.
    resp, rest = request(server, path, headers={"Range": "bytes=70000-"})
    assert resp.status == 206
    assert hashlib.sha256(partial + rest).hexdigest() == content_sha256(SIZE, 1)


def test_drop_applies_to_ranges_spanning_it(server: FaultServer) -> None:
    path = f"/file/a.bin?size={SIZE}&drop_at=70000"
    with pytest.raises(http.client.IncompleteRead) as exc:
        request(server, path, headers={"Range": "bytes=60000-99999"})
    assert len(exc.value.partial) == 10_000


# --- validators: ETag change, If-Range ---------------------------------------------------


def test_if_range_match_gives_206(server: FaultServer) -> None:
    path = f"/file/a.bin?size={SIZE}"
    first, _ = request(server, path, method="HEAD")
    for validator in (first.getheader("ETag"), first.getheader("Last-Modified")):
        assert validator
        resp, _ = request(server, path, headers={"Range": "bytes=0-9", "If-Range": validator})
        assert resp.status == 206


def test_etag_changes_mid_download(server: FaultServer) -> None:
    path = f"/file/a.bin?size={SIZE}&etag_after=1"
    first, body1 = request(server, path)
    etag1 = first.getheader("ETag")
    assert body1 == content_bytes(SIZE, 1)
    resp, body2 = request(server, path, headers={"Range": "bytes=100-", "If-Range": etag1 or ""})
    assert resp.status == 200  # validator mismatch: whole new representation
    assert resp.getheader("ETag") != etag1
    assert resp.getheader("Last-Modified") != first.getheader("Last-Modified")
    assert body2 == content_bytes(SIZE, content_seed(1, version=1))
    assert body2 != body1


def test_reset_clears_fault_state(server: FaultServer) -> None:
    path = "/file/a.bin?size=10&etag_after=1"
    etag1 = request(server, path)[0].getheader("ETag")
    assert request(server, path)[0].getheader("ETag") != etag1
    server.reset()
    assert request(server, path)[0].getheader("ETag") == etag1


# --- expired link -------------------------------------------------------------------------


def test_expired_link_returns_403(server: FaultServer) -> None:
    path = "/file/a.bin?size=10&expire_after=0.3"
    assert request(server, path)[0].status == 200
    time.sleep(0.4)
    assert request(server, path)[0].status == 403


# --- gzip -----------------------------------------------------------------------------------


def test_gzip_encoding(server: FaultServer) -> None:
    resp, body = request(server, f"/file/a.bin?size={SIZE}&gzip=1", headers={"Range": "bytes=0-9"})
    assert resp.status == 200
    assert resp.getheader("Content-Encoding") == "gzip"
    assert resp.getheader("Accept-Ranges") is None
    assert resp.getheader("Content-Length") == str(len(body))
    assert gzip.decompress(body) == content_bytes(SIZE, 1)


# --- cookie-protected route -------------------------------------------------------------------


def test_protected_requires_cookie(server: FaultServer) -> None:
    assert request(server, "/protected/p.bin?size=10")[0].status == 403
    resp, body = request(
        server, "/protected/p.bin?size=10", headers={"Cookie": f"{COOKIE_NAME}={COOKIE_VALUE}"}
    )
    assert resp.status == 200
    assert body == content_bytes(10, 1)


def test_set_cookie_route(server: FaultServer) -> None:
    resp, _ = request(server, "/set-cookie")
    assert resp.status == 200
    assert f"{COOKIE_NAME}={COOKIE_VALUE}" in (resp.getheader("Set-Cookie") or "")


# --- HEAD that fails or lies ------------------------------------------------------------------


def test_head_fail(server: FaultServer) -> None:
    assert request(server, "/file/a.bin?size=10&head=fail", method="HEAD")[0].status == 405
    assert request(server, "/file/a.bin?size=10&head=fail")[0].status == 200


def test_head_lies(server: FaultServer) -> None:
    head, _ = request(server, "/file/a.bin?size=10&head=lie", method="HEAD")
    assert head.getheader("Content-Length") == "0"
    _, body = request(server, "/file/a.bin?size=10&head=lie")
    assert len(body) == 10


# --- error statuses ------------------------------------------------------------------------------


@pytest.mark.parametrize("code", [404, 410, 500, 503])
def test_status_route(server: FaultServer, code: int) -> None:
    assert request(server, f"/status/{code}")[0].status == code


def test_unknown_route_is_404(server: FaultServer) -> None:
    assert request(server, "/nope")[0].status == 404


def test_bad_parameter_is_400(server: FaultServer) -> None:
    assert request(server, "/file/a.bin?size=lots")[0].status == 400
