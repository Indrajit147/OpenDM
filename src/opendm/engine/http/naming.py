"""Pick the filename for a download: Content-Disposition, then URL, then content type."""

from urllib.parse import unquote, urlsplit

from opendm.core.filenames import DEFAULT_NAME, sanitize_filename, split_ext
from opendm.discovery.content_types import extension_for
from opendm.engine.http.disposition import parse_content_disposition

# URL "extensions" that name the server script, not the file it returns.
_SCRIPT_EXTS = frozenset({".php", ".asp", ".aspx", ".jsp", ".cgi", ".pl", ".py", ".do"})


def filename_from_url(url: str) -> str | None:
    """Last path segment of the URL, percent-decoded; None if the path ends in '/'."""
    last = urlsplit(url).path.rsplit("/", 1)[-1]
    return unquote(last, errors="replace") or None


def choose_filename(content_disposition: str | None, url: str, content_type: str | None) -> str:
    """Sanitized filename for a response.

    ``url`` should be the final URL after redirects, as browsers do.
    """
    raw = parse_content_disposition(content_disposition) if content_disposition else None
    from_header = raw is not None
    if raw is None:
        raw = filename_from_url(url)
    name = sanitize_filename(raw, default="") if raw else ""
    type_ext = extension_for(content_type)
    if not name:
        return DEFAULT_NAME + type_ext
    stem, ext = split_ext(name)
    if not ext and type_ext:
        return sanitize_filename(name + type_ext)
    if not from_header and ext.lower() in _SCRIPT_EXTS and type_ext:
        return stem + type_ext
    return name
