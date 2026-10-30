"""Detect DRM-protected media (spec 2): such content is not supported, no workarounds.

Protected: HLS ``SAMPLE-AES``/``SAMPLE-AES-CTR`` or a DRM key system (FairPlay, Widevine,
PlayReady) and DASH Common Encryption / DRM ``ContentProtection``. Plain HLS AES-128,
whose key any player fetches from the playlist, is not DRM and is allowed (decision M5-2).
"""

import re
from typing import Any

PROTECTED_MESSAGE = "This content is protected (DRM). Protected content is not supported."

_DRM_KEY_SYSTEMS = (
    "com.apple.streamingkeydelivery",  # FairPlay
    "com.microsoft.playready",
    "com.widevine",
    "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",  # Widevine
    "9a04f079-9840-4286-ab92-e65be0885f95",  # PlayReady
    "94ce86fb-07ff-4f43-adb8-93d2fa968ca2",  # FairPlay
)
_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
_CONTENT_PROTECTION = re.compile(r"<\s*(?:\w+:)?ContentProtection\b[^>]*>", re.IGNORECASE)
_SCHEME = re.compile(r'schemeIdUri\s*=\s*"([^"]*)"', re.IGNORECASE)


def hls_is_protected(playlist: str) -> bool:
    for line in playlist.splitlines():
        line = line.strip()
        if not line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
            continue
        attrs = {k: v.strip('"') for k, v in _ATTR.findall(line.split(":", 1)[1])}
        method = attrs.get("METHOD", "").upper()
        keyformat = attrs.get("KEYFORMAT", "").lower()
        if method.startswith("SAMPLE-AES"):
            return True
        if any(system in keyformat for system in _DRM_KEY_SYSTEMS):
            return True
    return False


def dash_is_protected(manifest: str) -> bool:
    """Any ContentProtection element means the stream is encrypted for a DRM system."""
    for element in _CONTENT_PROTECTION.findall(manifest):
        scheme = _SCHEME.search(element)
        if scheme is None:
            return True
        uri = scheme.group(1).lower()
        if uri.startswith("urn:mpeg:dash:mp4protection") or any(
            system in uri for system in _DRM_KEY_SYSTEMS
        ):
            return True
    return False


def info_is_protected(info: dict[str, Any]) -> bool:
    """yt-dlp's verdict: protected if flagged, or if every format is DRM-only."""
    if info.get("_has_drm"):
        return True
    formats = info.get("formats") or []
    return bool(formats) and all(f.get("has_drm") for f in formats)
