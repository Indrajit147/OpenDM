"""Where the tools come from (spec 6.8). Only these official locations are used."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Sources:
    ytdlp_api: str = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
    # Every yt-dlp download URL must start with this (the API's asset links are checked).
    ytdlp_download_prefix: str = "https://github.com/yt-dlp/yt-dlp/releases/download/"
    ffmpeg_zip: str = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    ffmpeg_sha256: str = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256"
    ffmpeg_version: str = "https://www.gyan.dev/ffmpeg/builds/release-version"


YTDLP_ASSET = "yt-dlp.exe"
YTDLP_SUMS = "SHA2-256SUMS"
YTDLP_HOME = "https://github.com/yt-dlp/yt-dlp"
FFMPEG_HOME = "https://www.gyan.dev/ffmpeg/builds/"


def parse_sums(text: str, filename: str | None) -> str | None:
    """SHA-256 for ``filename`` from a ``<hash>  <name>`` list (``*name`` = binary mode).

    With ``filename`` None the text is a single-hash ``.sha256`` file.
    """
    for line in text.splitlines():
        fields = line.strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        digest = fields[0].lower()
        if filename is None:
            return digest
        if len(fields) >= 2 and fields[1].lstrip("*") == filename:
            return digest
    return None
