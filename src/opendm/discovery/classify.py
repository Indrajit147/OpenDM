"""What kind of link is this: a direct file, a stream manifest, or a web page with media?"""

from enum import StrEnum
from urllib.parse import urlsplit

from opendm.discovery.content_types import parse_content_type
from opendm.engine.media.formats import QUALITIES


class LinkKind(StrEnum):
    FILE = "file"  # download directly with the HTTP engine
    MANIFEST = "manifest"  # HLS/DASH stream: yt-dlp
    PAGE = "page"  # web page: yt-dlp looks for media on it


_MANIFEST_TYPES = frozenset(
    {"application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl",
     "application/dash+xml"}
)  # fmt: skip
_PAGE_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def classify(url: str, content_type: str | None) -> LinkKind:
    path = urlsplit(url).path.lower()
    mime = parse_content_type(content_type)
    if path.endswith((".m3u8", ".mpd")) or mime in _MANIFEST_TYPES:
        return LinkKind.MANIFEST
    if mime in _PAGE_TYPES:
        return LinkKind.PAGE
    return LinkKind.FILE


def parse_quality(text: str) -> str:
    """CLI quality: ``best``, ``1080p``/``1080``, ``audio-mp3``/``mp3``, ``audio-m4a``/``m4a``."""
    value = text.strip().lower().removesuffix("p")
    if value in ("mp3", "m4a"):
        value = "audio-" + value
    if value not in QUALITIES:
        choices = "best, 2160p, 1440p, 1080p, 720p, 480p, 360p, mp3, m4a"
        raise ValueError(f"unknown quality {text!r}; use one of: {choices}")
    return value
