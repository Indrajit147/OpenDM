"""Plain data models shared by the engines, storage, CLI and (later) GUI."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

MAIN_QUEUE_ID = 1


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


class AfterAction(StrEnum):
    """What to do when a queue has finished (spec 6.3)."""

    NONE = "none"
    SLEEP = "sleep"
    SHUTDOWN = "shutdown"


ALL_DAYS = 0b1111111  # bit 0 = Monday ... bit 6 = Sunday


@dataclass
class Queue:
    name: str
    id: int | None = None
    max_concurrent: int = 3
    enabled: bool = True
    start_time: str | None = None  # "HH:MM", local time
    stop_time: str | None = None
    days: int = ALL_DAYS
    after_action: AfterAction = AfterAction.NONE
    position: int = 0

    @property
    def scheduled(self) -> bool:
        return self.enabled and self.start_time is not None


@dataclass
class Category:
    name: str
    extensions: tuple[str, ...] = ()  # lowercase, without dots; may be "tar.gz"
    folder: str = ""  # "" = base download folder; relative = inside it; absolute = as is
    fallback: bool = False  # used when no extension matches
    id: int | None = None
    position: int = 0


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Job:
    """A download as stored in the database."""

    request: DownloadRequest
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    queue_id: int = MAIN_QUEUE_ID
    category_id: int | None = None
    position: int = 0
    state: JobState = JobState.QUEUED
    message: str = ""
    final_path: Path | None = None
    size: int | None = None
    downloaded: int = 0
    connections: int | None = None  # None = engine default
    relinked: bool = False  # the URL was refreshed; continue the partial file from it
    media_options: dict[str, Any] | None = None  # set for yt-dlp (media) jobs
    error_kind: str | None = None
    error_message: str | None = None
    sha256: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def kind(self) -> str:
        return "media" if self.media_options is not None else "http"

    @property
    def name(self) -> str:
        """File name if known, else the last URL path segment (never the query string)."""
        if self.final_path is not None:
            return self.final_path.name
        if self.request.filename:
            return self.request.filename
        last = urlsplit(self.request.url).path.rsplit("/", 1)[-1]
        return unquote(last, errors="replace") or self.request.url
