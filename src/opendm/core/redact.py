"""Remove secrets before anything reaches a log or an error message (spec 6.11)."""

from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

REDACTED = "<redacted>"
SECRET_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})


def redact_url(url: str) -> str:
    """Drop user info, query string and fragment (they often carry tokens)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
    except ValueError:
        return REDACTED
    query = REDACTED if parts.query else ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: REDACTED if k.lower() in SECRET_HEADERS else v for k, v in headers.items()}
