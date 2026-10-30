"""Find out what a URL serves before downloading it (spec 6.1, "Probe")."""

from collections.abc import Mapping

from opendm.core.errors import DownloadError, ErrorKind, error_from_status
from opendm.core.models import ProbeResult
from opendm.engine.http.naming import choose_filename
from opendm.engine.http.transport import Response, Transport, validate_url

# HEAD failures worth retrying as GET; anything else (TLS, bad URL) is final.
_FALLBACK_KINDS = frozenset({ErrorKind.NETWORK, ErrorKind.TIMEOUT})


def content_length(headers: Mapping[str, str]) -> int | None:
    """Body size from Content-Length, unless a Content-Encoding makes it meaningless."""
    encoding = headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        return None
    try:
        value = int(headers.get("content-length", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def total_from_content_range(value: str | None) -> int | None:
    """``bytes 0-0/1234`` or ``bytes */1234`` -> 1234; None if unknown or invalid."""
    if not value:
        return None
    _, _, total = value.rpartition("/")
    try:
        return int(total)
    except ValueError:
        return None


def _result(url: str, resp: Response, size: int | None, accepts_ranges: bool) -> ProbeResult:
    headers = resp.headers
    return ProbeResult(
        url=url,
        final_url=resp.url,
        size=size,
        accepts_ranges=accepts_ranges,
        etag=headers.get("etag"),
        last_modified=headers.get("last-modified"),
        content_type=headers.get("content-type"),
        filename=choose_filename(
            headers.get("content-disposition"), resp.url, headers.get("content-type")
        ),
    )


async def probe(
    transport: Transport, url: str, headers: Mapping[str, str] | None = None
) -> ProbeResult:
    """HEAD first; fall back to ``GET Range: bytes=0-0`` if HEAD fails or gives no size.

    The GET body is never read beyond the headers.
    """
    validate_url(url)
    headers = dict(headers or {})
    try:
        async with transport.stream("HEAD", url, headers) as resp:
            if 200 <= resp.status < 300:
                size = content_length(resp.headers)
                if size:  # 0 or missing: HEAD may be lying, ask with GET
                    ranges = "bytes" in resp.headers.get("accept-ranges", "").lower()
                    return _result(url, resp, size, ranges)
    except DownloadError as exc:
        if exc.kind not in _FALLBACK_KINDS:
            raise

    async with transport.stream("GET", url, {**headers, "Range": "bytes=0-0"}) as resp:
        if resp.status == 206:
            return _result(
                url, resp, total_from_content_range(resp.headers.get("content-range")), True
            )
        if resp.status == 416:  # empty resource
            total = total_from_content_range(resp.headers.get("content-range"))
            return _result(url, resp, total, False)
        if 200 <= resp.status < 300:
            return _result(url, resp, content_length(resp.headers), False)
        raise error_from_status(resp.status)
