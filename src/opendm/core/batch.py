"""Batch downloads: ``file[01-20].zip`` patterns and pasted/dropped URL lists."""

import itertools
import re

from opendm.core.errors import DownloadError
from opendm.engine.http.transport import validate_url

MAX_EXPANSION = 10_000
_RANGE = re.compile(r"\[([^\]\[]+)-([^\]\[]+)\]")
_BROKEN = re.compile(r"\[[^\]\[]*-[^\]\[]*\]")  # a bracketed range that did not match _RANGE


class BatchError(ValueError):
    pass


def _expand_range(first: str, last: str) -> list[str]:
    if first.isdigit() and last.isdigit():
        width = len(first) if first.startswith("0") and len(first) > 1 else 1
        a, b = int(first), int(last)
        step = 1 if b >= a else -1
        if abs(b - a) + 1 > MAX_EXPANSION:
            raise BatchError(f"range [{first}-{last}] is too large")
        return [str(n).zfill(width) for n in range(a, b + step, step)]
    if len(first) == 1 and len(last) == 1 and first.isalpha() and last.isalpha():
        a, b = ord(first), ord(last)
        step = 1 if b >= a else -1
        return [chr(c) for c in range(a, b + step, step)]
    raise BatchError(f"cannot expand [{first}-{last}]: use numbers or single letters")


def expand_pattern(pattern: str) -> list[str]:
    """Expand every ``[a-b]`` range (numbers keep zero padding, letters a-z)."""
    parts = _RANGE.split(pattern)
    literals = parts[0::3]
    if any(_BROKEN.search(literal) for literal in literals):
        raise BatchError(f"incomplete range in {pattern!r}; write it like [1-20] or [a-z]")
    ranges = [_expand_range(a, b) for a, b in zip(parts[1::3], parts[2::3], strict=True)]
    total = 1
    for r in ranges:
        total *= len(r)
    if total > MAX_EXPANSION:
        raise BatchError(f"pattern expands to {total} URLs (limit {MAX_EXPANSION})")
    results = []
    for combo in itertools.product(*ranges):
        out = literals[0]
        for value, literal in zip(combo, literals[1:], strict=True):
            out += value + literal
        results.append(out)
    return results


def parse_url_list(text: str) -> tuple[list[str], list[str]]:
    """URLs from text (one per line, ``#`` comments, patterns expanded, duplicates dropped).

    Returns (valid http/https URLs, rejected lines).
    """
    urls: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            expanded = expand_pattern(line)
            for url in expanded:
                validate_url(url)
        except (BatchError, DownloadError):
            rejected.append(line)
            continue
        for url in expanded:
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls, rejected
