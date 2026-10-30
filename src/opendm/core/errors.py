"""Error model shared by every engine. Retry policy (M2) keys off ``ErrorKind``."""

import errno
from enum import StrEnum


class ErrorKind(StrEnum):
    NETWORK = "network"  # connection reset/refused, body cut short
    TIMEOUT = "timeout"
    SERVER = "server"  # 5xx, 408, 429
    NOT_FOUND = "not_found"  # 404, 410
    LINK_EXPIRED = "link_expired"  # 403: access denied or the signed link expired
    HTTP_CLIENT = "http_client"  # other 4xx, too many redirects, bad range reply
    DISK_FULL = "disk_full"
    PERMISSION = "permission"
    PATH_TOO_LONG = "path_too_long"
    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    TLS = "tls"
    UNKNOWN = "unknown"


RETRYABLE_KINDS = frozenset({ErrorKind.NETWORK, ErrorKind.TIMEOUT, ErrorKind.SERVER})

# Windows system error codes that arrive as OSError.winerror.
_WIN_DISK_FULL = {39, 112}  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
_WIN_ACCESS = {5, 32, 33}  # access denied, sharing violation, lock violation
_WIN_PATH_TOO_LONG = {206}  # ERROR_FILENAME_EXCED_RANGE


class DownloadError(Exception):
    """A download failure with a machine-readable kind."""

    def __init__(self, kind: ErrorKind, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS

    def __repr__(self) -> str:
        return f"DownloadError({self.kind!s}, {self.message!r}, status={self.status})"


def kind_for_status(status: int) -> ErrorKind:
    """Classify a non-success HTTP status code."""
    if status in (404, 410):
        return ErrorKind.NOT_FOUND
    if status == 403:
        return ErrorKind.LINK_EXPIRED
    if status in (408, 429) or status >= 500:
        return ErrorKind.SERVER
    return ErrorKind.HTTP_CLIENT


def error_from_status(status: int) -> DownloadError:
    return DownloadError(kind_for_status(status), f"server replied HTTP {status}", status=status)


def error_from_os(exc: OSError) -> DownloadError:
    """Classify a filesystem error."""
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerror in _WIN_DISK_FULL:
        kind = ErrorKind.DISK_FULL
    elif isinstance(exc, PermissionError) or winerror in _WIN_ACCESS:
        kind = ErrorKind.PERMISSION
    elif exc.errno == errno.ENAMETOOLONG or winerror in _WIN_PATH_TOO_LONG:
        kind = ErrorKind.PATH_TOO_LONG
    else:
        kind = ErrorKind.UNKNOWN
    return DownloadError(kind, exc.strerror or str(exc))
