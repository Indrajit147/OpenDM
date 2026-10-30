"""Probe against the local test server."""

import socket
from collections.abc import AsyncIterator
from urllib.parse import quote

import pytest

from opendm.core.errors import DownloadError, ErrorKind
from opendm.engine.http.probe import probe
from opendm.engine.http.transport import HttpxTransport, validate_url
from tests.server.app import COOKIE_NAME, COOKIE_VALUE, FaultServer

SIZE = 300_000


@pytest.fixture
async def transport() -> AsyncIterator[HttpxTransport]:
    t = HttpxTransport()
    yield t
    await t.aclose()


async def _kind(transport: HttpxTransport, url: str) -> ErrorKind:
    with pytest.raises(DownloadError) as exc:
        await probe(transport, url)
    return exc.value.kind


async def test_probe_normal(server: FaultServer, transport: HttpxTransport) -> None:
    url = server.url(f"/file/a.bin?size={SIZE}&type=video/mp4")
    result = await probe(transport, url)
    assert result.size == SIZE
    assert result.accepts_ranges
    assert result.etag and result.last_modified
    assert result.validator == result.etag
    assert result.content_type == "video/mp4"
    assert result.final_url == url
    assert result.filename == "a.bin"


async def test_probe_without_range_support(server: FaultServer, transport) -> None:
    result = await probe(transport, server.url(f"/file/a.bin?size={SIZE}&range=none"))
    assert result.size == SIZE
    assert not result.accepts_ranges


@pytest.mark.parametrize("head", ["fail", "lie", "nolength"])
async def test_probe_falls_back_to_range_get(server: FaultServer, transport, head: str) -> None:
    result = await probe(transport, server.url(f"/file/a.bin?size={SIZE}&head={head}"))
    assert result.size == SIZE
    assert result.accepts_ranges


async def test_probe_unknown_size(server: FaultServer, transport) -> None:
    result = await probe(transport, server.url("/file/a.bin?size=1000&length=none&range=none"))
    assert result.size is None
    assert not result.accepts_ranges


async def test_probe_gzip_size_is_unknown(server: FaultServer, transport) -> None:
    result = await probe(transport, server.url(f"/file/a.bin?size={SIZE}&gzip=1"))
    assert result.size is None
    assert not result.accepts_ranges


async def test_probe_follows_redirects(server: FaultServer, transport) -> None:
    target = "/file/final-name.bin?size=10"
    result = await probe(transport, server.url("/redirect/2?to=" + quote(target, safe="")))
    assert result.final_url == server.url(target)
    assert result.filename == "final-name.bin"
    assert result.size == 10


async def test_probe_uses_content_disposition(server: FaultServer, transport) -> None:
    name = "রিপোর্ট € file.pdf"
    result = await probe(transport, server.url(f"/file/x.bin?size=10&cd={quote(name)}"))
    assert result.filename == name


async def test_probe_sends_headers(server: FaultServer, transport) -> None:
    url = server.url("/protected/p.bin?size=10")
    assert await _kind(transport, url) is ErrorKind.LINK_EXPIRED
    result = await probe(transport, url, {"Cookie": f"{COOKIE_NAME}={COOKIE_VALUE}"})
    assert result.size == 10


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/status/404", ErrorKind.NOT_FOUND),
        ("/status/410", ErrorKind.NOT_FOUND),
        ("/status/500", ErrorKind.SERVER),
        ("/file/a.bin?size=10&expire_after=0", ErrorKind.LINK_EXPIRED),
    ],
)
async def test_probe_http_errors(server: FaultServer, transport, path: str, kind) -> None:
    assert await _kind(transport, server.url(path)) is kind


async def test_probe_connection_refused(transport) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # No GET fallback after a failed connect: Windows spends ~2 s per refused attempt.
    assert await _kind(transport, f"http://127.0.0.1:{port}/x") is ErrorKind.CONNECTION


async def test_probe_timeout(server: FaultServer) -> None:
    t = HttpxTransport(read_timeout=0.3)
    try:
        assert await _kind(t, server.url("/file/a.bin?size=10&slow_start=1.5")) is ErrorKind.TIMEOUT
    finally:
        await t.aclose()


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("ftp://example.com/a.zip", ErrorKind.UNSUPPORTED_SCHEME),
        ("file:///C:/Windows/win.ini", ErrorKind.UNSUPPORTED_SCHEME),
        ("javascript:alert(1)", ErrorKind.UNSUPPORTED_SCHEME),
        ("http://", ErrorKind.INVALID_URL),
        ("not a url", ErrorKind.UNSUPPORTED_SCHEME),
        ("http://exa mple.com/", ErrorKind.INVALID_URL),
    ],
)
def test_validate_url_rejects(url: str, kind: ErrorKind) -> None:
    with pytest.raises(DownloadError) as exc:
        validate_url(url)
    assert exc.value.kind is kind


def test_validate_url_accepts() -> None:
    validate_url("https://example.com/a.zip")
    validate_url("HTTP://Example.com:8080/a b.zip")
