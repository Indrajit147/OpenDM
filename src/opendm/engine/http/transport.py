"""HTTP transport interface and its httpx implementation (decision D3).

Engines depend only on ``Transport``/``Response`` so the client can be swapped.
Every httpx exception is translated into a ``DownloadError`` here.
"""

import ssl
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from opendm import __version__
from opendm.core.branding import APP_NAME
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.redact import redact_url

DEFAULT_USER_AGENT = f"{APP_NAME}/{__version__}"
ALLOWED_SCHEMES = frozenset({"http", "https"})
_BAD_HOST_CHARS = frozenset(' <>"{}|\\^`')


class Response(Protocol):
    @property
    def status(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...  # case-insensitive
    @property
    def url(self) -> str: ...  # final URL after redirects
    def aiter_bytes(self) -> AsyncIterator[bytes]: ...


class Transport(Protocol):
    def stream(
        self, method: str, url: str, headers: Mapping[str, str] | None = None
    ) -> AbstractAsyncContextManager[Response]: ...

    async def aclose(self) -> None: ...


def validate_url(url: str) -> None:
    """Allow only well-formed http(s) URLs (spec 6.6)."""
    try:
        parts = urlsplit(url.strip())
        _ = parts.port  # raises ValueError for a bad port
    except ValueError as exc:
        raise DownloadError(ErrorKind.INVALID_URL, f"invalid URL: {exc}") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        scheme = parts.scheme or "(none)"
        raise DownloadError(ErrorKind.UNSUPPORTED_SCHEME, f"unsupported URL scheme: {scheme}")
    host = parts.hostname
    if not host or any(c in _BAD_HOST_CHARS or c.isspace() for c in host):
        raise DownloadError(ErrorKind.INVALID_URL, "invalid URL: missing or malformed host")


def error_from_httpx(exc: Exception, url: str) -> DownloadError:
    where = redact_url(url)
    if isinstance(exc, httpx.TimeoutException):
        return DownloadError(ErrorKind.TIMEOUT, f"timed out talking to {where}")
    if isinstance(exc, httpx.UnsupportedProtocol):
        return DownloadError(ErrorKind.UNSUPPORTED_SCHEME, f"unsupported URL: {where}")
    if isinstance(exc, httpx.InvalidURL):
        return DownloadError(ErrorKind.INVALID_URL, f"invalid URL: {where}")
    if isinstance(exc, httpx.TooManyRedirects):
        return DownloadError(ErrorKind.HTTP_CLIENT, f"too many redirects: {where}")
    if isinstance(exc, httpx.ConnectError):
        if _is_tls_error(exc):
            return DownloadError(ErrorKind.TLS, f"TLS certificate check failed for {where}")
        return DownloadError(ErrorKind.CONNECTION, f"could not connect to {where}")
    return DownloadError(ErrorKind.NETWORK, f"network error ({type(exc).__name__}): {where}")


def _is_tls_error(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(seen):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


class _HttpxResponse:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def status(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    @property
    def url(self) -> str:
        return str(self._response.url)

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        # Decodes Content-Encoding (gzip etc.) if a server ignores Accept-Encoding.
        return self._response.aiter_bytes()


class HttpxTransport:
    """httpx.AsyncClient with download-friendly defaults.

    Uses the system proxy (environment/registry) unless ``proxy`` is given, follows
    redirects and verifies TLS unless told otherwise.
    """

    def __init__(
        self,
        *,
        verify: bool = True,
        connect_timeout: float = 15.0,
        read_timeout: float = 30.0,
        max_redirects: int = 10,
        proxy: str | None = None,
        use_system_proxy: bool = True,
    ) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=max_redirects,
            verify=verify,
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            proxy=proxy,
            trust_env=use_system_proxy and proxy is None,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept-Encoding": "identity"},
        )

    @asynccontextmanager
    async def stream(
        self, method: str, url: str, headers: Mapping[str, str] | None = None
    ) -> AsyncIterator[Response]:
        try:
            async with self._client.stream(method, url, headers=dict(headers or {})) as resp:
                yield _HttpxResponse(resp)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise error_from_httpx(exc, url) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
