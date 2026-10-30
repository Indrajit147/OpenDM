"""Error model, progress metering, unit formatting and redaction."""

import errno

import pytest

from opendm.core.errors import DownloadError, ErrorKind, error_from_os, kind_for_status
from opendm.core.models import DownloadRequest
from opendm.core.progress import SpeedMeter, Throttle, eta_seconds
from opendm.core.redact import redact_headers, redact_url
from opendm.core.units import format_bytes, format_duration


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


# --- errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (404, ErrorKind.NOT_FOUND),
        (410, ErrorKind.NOT_FOUND),
        (403, ErrorKind.LINK_EXPIRED),
        (401, ErrorKind.HTTP_CLIENT),
        (400, ErrorKind.HTTP_CLIENT),
        (408, ErrorKind.SERVER),
        (429, ErrorKind.SERVER),
        (500, ErrorKind.SERVER),
        (503, ErrorKind.SERVER),
    ],
)
def test_kind_for_status(status: int, kind: ErrorKind) -> None:
    assert kind_for_status(status) is kind


def test_retryable_kinds() -> None:
    assert DownloadError(ErrorKind.CONNECTION, "x").retryable
    assert DownloadError(ErrorKind.NETWORK, "x").retryable
    assert DownloadError(ErrorKind.TIMEOUT, "x").retryable
    assert DownloadError(ErrorKind.SERVER, "x", status=503).retryable
    assert not DownloadError(ErrorKind.NOT_FOUND, "x", status=404).retryable
    assert not DownloadError(ErrorKind.DISK_FULL, "x").retryable


def test_error_str_includes_message() -> None:
    err = DownloadError(ErrorKind.NOT_FOUND, "HTTP 404", status=404)
    assert "HTTP 404" in str(err)
    assert err.status == 404


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (OSError(errno.ENOSPC, "No space left"), ErrorKind.DISK_FULL),
        (PermissionError(errno.EACCES, "Access denied"), ErrorKind.PERMISSION),
        (OSError(errno.ENAMETOOLONG, "Name too long"), ErrorKind.PATH_TOO_LONG),
        (OSError(errno.EIO, "I/O error"), ErrorKind.UNKNOWN),
    ],
)
def test_error_from_os(exc: OSError, kind: ErrorKind) -> None:
    assert error_from_os(exc).kind is kind


def test_error_from_os_windows_disk_full() -> None:
    exc = OSError(errno.EINVAL, "disk full")
    exc.winerror = 112  # type: ignore[attr-defined]  # ERROR_DISK_FULL
    assert error_from_os(exc).kind is ErrorKind.DISK_FULL


# --- request headers -----------------------------------------------------------


def test_request_headers_merge(tmp_path) -> None:
    req = DownloadRequest(
        url="http://x/a",
        dest_dir=tmp_path,
        headers={"X-Test": "1"},
        user_agent="UA/1",
        referrer="http://x/page",
        cookies="a=b",
    )
    assert req.request_headers() == {
        "X-Test": "1",
        "User-Agent": "UA/1",
        "Referer": "http://x/page",
        "Cookie": "a=b",
    }


def test_request_headers_minimal(tmp_path) -> None:
    assert DownloadRequest(url="http://x/a", dest_dir=tmp_path).request_headers() == {}


# --- progress ---------------------------------------------------------------------


def test_speed_meter_average_over_window() -> None:
    clock = FakeClock()
    meter = SpeedMeter(window=2.0, clock=clock)
    meter.reset(0)
    for _ in range(4):
        clock.now += 0.5
        meter.update(meter.total + 1000)
    assert meter.speed() == pytest.approx(2000.0)


def test_speed_meter_drops_to_zero_when_stalled() -> None:
    clock = FakeClock()
    meter = SpeedMeter(window=2.0, clock=clock)
    meter.reset(0)
    clock.now += 1
    meter.update(5000)
    clock.now += 10
    assert meter.speed() == 0.0


def test_speed_meter_reset_with_offset() -> None:
    clock = FakeClock()
    meter = SpeedMeter(window=2.0, clock=clock)
    meter.reset(10_000)
    clock.now += 1
    meter.update(11_000)
    assert meter.speed() == pytest.approx(1000.0)


def test_eta() -> None:
    assert eta_seconds(total=1000, done=500, speed=100) == pytest.approx(5.0)
    assert eta_seconds(total=None, done=500, speed=100) is None
    assert eta_seconds(total=1000, done=500, speed=0) is None


def test_throttle() -> None:
    clock = FakeClock()
    throttle = Throttle(0.25, clock=clock)
    assert throttle.ready()
    assert not throttle.ready()
    clock.now += 0.3
    assert throttle.ready()


# --- units --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "text"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KiB"), (1536, "1.5 KiB"), (5 * 1024**3, "5.0 GiB")],
)
def test_format_bytes(n: int, text: str) -> None:
    assert format_bytes(n) == text


@pytest.mark.parametrize(
    ("seconds", "text"), [(None, "--:--"), (0, "0:00"), (65, "1:05"), (3725, "1:02:05")]
)
def test_format_duration(seconds: float | None, text: str) -> None:
    assert format_duration(seconds) == text


# --- redaction ------------------------------------------------------------------------


def test_redact_url_strips_query_fragment_and_userinfo() -> None:
    assert (
        redact_url("https://user:pw@example.com/a/b.zip?token=SECRET#frag")
        == "https://example.com/a/b.zip?<redacted>"
    )
    assert redact_url("https://example.com/a.zip") == "https://example.com/a.zip"


def test_redact_headers() -> None:
    redacted = redact_headers({"Cookie": "a=b", "authorization": "Bearer x", "Referer": "r"})
    assert redacted == {"Cookie": "<redacted>", "authorization": "<redacted>", "Referer": "r"}
