"""Content-Disposition filename parsing per RFC 6266, with RFC 5987 ext-values.

Lenient on purpose: real servers send missing disposition types, spaces around
"=", raw UTF-8 bytes and percent-encoded plain filenames.
"""

from urllib.parse import unquote

_EXT_CHARSETS = ("utf-8", "iso-8859-1")


def _split_params(value: str) -> dict[str, str]:
    """Parse ``type; name=value; name="quoted"`` into lowercase-keyed params.

    The first occurrence of a parameter wins (duplicates are invalid anyway).
    """
    params: dict[str, str] = {}
    i, n = 0, len(value)
    while i < n:
        while i < n and value[i] in " \t;":
            i += 1
        start = i
        while i < n and value[i] not in "=;":
            i += 1
        name = value[start:i].strip().lower()
        if i >= n or value[i] == ";":
            continue  # bare token such as the disposition type
        i += 1  # skip "="
        while i < n and value[i] in " \t":
            i += 1
        if i < n and value[i] == '"':
            i += 1
            chars: list[str] = []
            while i < n and value[i] != '"':
                if value[i] == "\\" and i + 1 < n:
                    i += 1
                chars.append(value[i])
                i += 1
            param = "".join(chars)
            while i < n and value[i] != ";":
                i += 1
        else:
            start = i
            while i < n and value[i] != ";":
                i += 1
            param = value[start:i].strip()
        if name:
            params.setdefault(name, param)
    return params


def _decode_ext_value(value: str) -> str | None:
    """Decode ``charset'lang'percent-encoded`` (RFC 5987); None if invalid."""
    charset, sep, rest = value.partition("'")
    _lang, sep2, encoded = rest.partition("'")
    charset = charset.strip().lower()
    if not (sep and sep2) or charset not in _EXT_CHARSETS:
        return None
    try:
        return unquote(encoded, encoding=charset, errors="strict")
    except UnicodeDecodeError:
        return None


def _fix_mojibake(name: str) -> str:
    """Undo raw UTF-8 bytes that an HTTP layer decoded as Latin-1."""
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _percent_decode(name: str) -> str:
    """Decode %XX escapes in a plain filename only if they form valid UTF-8."""
    if "%" not in name:
        return name
    try:
        return unquote(name, errors="strict")
    except UnicodeDecodeError:
        return name


def parse_content_disposition(value: str) -> str | None:
    """Return the (unsanitized) filename from a Content-Disposition value, if any."""
    params = _split_params(value)
    ext_value = params.get("filename*")
    if ext_value:
        decoded = _decode_ext_value(ext_value)
        if decoded:
            return decoded
    name = params.get("filename")
    if not name:
        return None
    return _percent_decode(_fix_mojibake(name)) or None
