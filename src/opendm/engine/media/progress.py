"""Parse yt-dlp's output into progress, phases, the final path and classified errors.

We ask yt-dlp for one space-separated progress line per update (``--newline`` plus
``--progress-template``) and print the final path after post-processing.
"""

import re
from typing import Any

from opendm.core.errors import DownloadError, ErrorKind
from opendm.engine.media.drm import PROTECTED_MESSAGE

PROGRESS_MARK = "OPENDM_PROGRESS"
FILE_MARK = "OPENDM_FILE:"
PROGRESS_TEMPLATE = (
    f"download:{PROGRESS_MARK} %(progress.status)s %(progress.downloaded_bytes)s "
    "%(progress.total_bytes)s %(progress.total_bytes_estimate)s %(progress.speed)s "
    "%(progress.eta)s %(info.format_id)s"
)
FILE_TEMPLATE = f"after_move:{FILE_MARK}%(filepath)s"
PLANNED_MARK = "OPENDM_PLANNED:"
PLANNED_TEMPLATE = f"before_dl:{PLANNED_MARK}%(filename)s"
_PHASES = {
    "[Merger]": "merging",
    "[ExtractAudio]": "converting",
    "[VideoRemuxer]": "converting",
    "[VideoConvertor]": "converting",
    "[EmbedThumbnail]": "converting",
    "[FFmpegSubtitlesConvertor]": "converting",
    "[FixupM3u8]": "converting",
}


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None  # "NA"


def parse_line(line: str) -> tuple[str, Any] | None:
    """("progress", dict) | ("file", path) | ("phase", name) | None."""
    line = line.rstrip("\r\n")
    if line.startswith(PROGRESS_MARK + " "):
        fields = line.split(" ")
        if len(fields) < 8:
            return None
        _, status, done, total, estimate, speed, eta, format_id = fields[:8]
        size = _number(total) or _number(estimate)
        downloaded = _number(done)
        return "progress", {
            "status": status,
            "downloaded": int(downloaded) if downloaded is not None else 0,
            "total": int(size) if size is not None else None,
            "speed": _number(speed),
            "eta": _number(eta),
            "format_id": format_id,
        }
    if line.startswith(FILE_MARK):
        return "file", line[len(FILE_MARK) :].strip()
    if line.startswith(PLANNED_MARK):
        return "planned", line[len(PLANNED_MARK) :].strip()
    for prefix, phase in _PHASES.items():
        if line.startswith(prefix):
            return "phase", phase
    return None


class ProgressTracker:
    """Overall progress across the separate files of one download (video + audio)."""

    def __init__(self) -> None:
        self._parts: dict[str, tuple[int, int | None]] = {}

    def update(self, data: dict[str, Any]) -> None:
        key = data.get("format_id") or "?"
        self._parts[key] = (data["downloaded"], data["total"])

    @property
    def downloaded(self) -> int:
        return sum(done for done, _ in self._parts.values())

    @property
    def total(self) -> int | None:
        totals = [total for _, total in self._parts.values()]
        if not totals or any(t is None for t in totals):
            return None
        return sum(t for t in totals if t is not None)


_HTTP_ERROR = re.compile(r"HTTP Error (\d{3})")


def classify_ytdlp_error(stderr: str) -> DownloadError:
    """Turn yt-dlp's last ERROR line into a DownloadError."""
    errors = [line for line in stderr.splitlines() if line.startswith("ERROR:")]
    text = errors[-1].removeprefix("ERROR:").strip() if errors else stderr.strip()
    lower = text.lower()
    if "drm" in lower:
        return DownloadError(ErrorKind.PROTECTED, PROTECTED_MESSAGE)
    status = _HTTP_ERROR.search(text)
    if status:
        code = int(status.group(1))
        if code == 403:
            return DownloadError(ErrorKind.LINK_EXPIRED, text, status=code)
        if code in (404, 410):
            return DownloadError(ErrorKind.NOT_FOUND, text, status=code)
        if code >= 500 or code == 429:
            return DownloadError(ErrorKind.SERVER, text, status=code)
    if any(word in lower for word in ("timed out", "unable to download webpage",
                                      "connection", "getaddrinfo")):  # fmt: skip
        return DownloadError(ErrorKind.NETWORK, text)
    return DownloadError(ErrorKind.MEDIA, text or "yt-dlp failed without a message")
