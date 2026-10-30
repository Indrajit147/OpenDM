"""Plain data models shared by the engines, CLI and (later) GUI."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class JobState(StrEnum):
    QUEUED = "queued"
    PROBING = "probing"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadRequest:
    """What the user asked for. ``filename`` overrides the detected name."""

    url: str
    dest_dir: Path
    filename: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str | None = None
    referrer: str | None = None
    cookies: str | None = None
    verify_tls: bool = True
    checksum: str | None = None  # "sha256:<hex>", "sha1:<hex>" or "md5:<hex>"
    speed_limit: int | None = None  # bytes per second for this download
    restart: bool = False  # discard an existing partial download of the same URL
    part_file: Path | None = None  # continue this partial file (URL may be a refreshed link)

    def request_headers(self) -> dict[str, str]:
        """Headers to send with every request for this download."""
        headers = dict(self.headers)
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if self.referrer:
            headers["Referer"] = self.referrer
        if self.cookies:
            headers["Cookie"] = self.cookies
        return headers


@dataclass(frozen=True)
class ProbeResult:
    """What the server told us about the resource before downloading."""

    url: str
    final_url: str
    size: int | None
    accepts_ranges: bool
    etag: str | None
    last_modified: str | None
    content_type: str | None
    filename: str

    @property
    def validator(self) -> str | None:
        """Value for If-Range: a strong ETag if there is one, else Last-Modified."""
        if self.etag and not self.etag.startswith("W/"):
            return self.etag
        return self.last_modified


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size: int
    sha256: str
