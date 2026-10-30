"""State sidecar, file lock and positioned writer."""

import json
from pathlib import Path

import pytest

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.models import ProbeResult
from opendm.engine.http.resume import (
    STATE_VERSION,
    DownloadState,
    FileLock,
    load_state,
    mismatch_reason,
    save_state,
    url_hash,
)
from opendm.engine.http.writer import PartFile


def probe_result(**overrides: object) -> ProbeResult:
    values: dict[str, object] = {
        "url": "http://h/a.bin?token=SECRET",
        "final_url": "http://cdn/a.bin",
        "size": 1000,
        "accepts_ranges": True,
        "etag": '"abc"',
        "last_modified": "Thu, 01 Jan 2026 00:00:00 GMT",
        "content_type": "application/octet-stream",
        "filename": "a.bin",
    }
    values.update(overrides)
    return ProbeResult(**values)  # type: ignore[arg-type]


def make_state() -> DownloadState:
    return DownloadState.from_probe(probe_result(), [(0, 500, 200), (500, 1000, 0)])


# --- sidecar --------------------------------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "a.bin.odm-state"
    save_state(path, make_state())
    loaded = load_state(path)
    assert loaded == make_state()
    assert loaded is not None and loaded.written == 200
    assert not list(tmp_path.glob("*.tmp"))  # temp file was renamed away


def test_state_never_contains_cookies_or_headers(tmp_path: Path) -> None:
    path = tmp_path / "s"
    save_state(path, make_state())
    text = path.read_text("utf-8")
    assert "cookie" not in text.lower() and "header" not in text.lower()
    assert "SECRET" not in text and "http" not in text  # only a hash of the URL is kept
    assert json.loads(text)["version"] == STATE_VERSION


def test_url_hash_identifies_the_request_url() -> None:
    state = make_state()
    assert state.url_hash == url_hash("http://h/a.bin?token=SECRET")
    assert state.url_hash != url_hash("http://h/a.bin?token=OTHER")


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        '{"version": 999}',
        '{"version": 1, "url_hash": "x"}',
        '{"version": 1, "url_hash": "u", "size": 10, "etag": null, '
        '"last_modified": null, "accepts_ranges": true, "segments": [[0, 5, 9]]}',
        '{"version": 1, "url_hash": "u", "size": 10, "etag": null, '
        '"last_modified": null, "accepts_ranges": true, "segments": [[0, 5, 0], [6, 10, 0]]}',
    ],
)
def test_load_rejects_damaged_files(tmp_path: Path, content: str) -> None:
    path = tmp_path / "s"
    path.write_text(content, "utf-8")
    assert load_state(path) is None


def test_load_missing_file(tmp_path: Path) -> None:
    assert load_state(tmp_path / "nope") is None


def test_mismatch_reason() -> None:
    state = make_state()
    assert mismatch_reason(state, probe_result()) is None
    assert "size" in (mismatch_reason(state, probe_result(size=999)) or "")
    assert "ETag" in (mismatch_reason(state, probe_result(etag='"other"')) or "")
    # no ETag on either side: Last-Modified decides
    no_etag = DownloadState.from_probe(probe_result(etag=None), [(0, 1000, 10)])
    assert mismatch_reason(no_etag, probe_result(etag=None)) is None
    changed = probe_result(etag=None, last_modified="Fri, 02 Jan 2026 00:00:00 GMT")
    assert "Last-Modified" in (mismatch_reason(no_etag, changed) or "")
    # no validator at all: cannot prove it is the same file
    bare = DownloadState.from_probe(probe_result(etag=None, last_modified=None), [(0, 1000, 1)])
    assert mismatch_reason(bare, probe_result(etag=None, last_modified=None))


# --- lock --------------------------------------------------------------------------------


def test_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "a.bin.odm-lock"
    first = FileLock(path)
    first.acquire()
    second = FileLock(path)
    with pytest.raises(DownloadError) as exc:
        second.acquire()
    assert exc.value.kind is ErrorKind.IN_USE
    first.release()
    second.acquire()  # free again
    second.release()
    assert not path.exists()


def test_stale_lock_file_is_not_locked(tmp_path: Path) -> None:
    path = tmp_path / "a.bin.odm-lock"
    path.write_text("12345")  # left behind by a killed process
    lock = FileLock(path)
    lock.acquire()
    lock.release()


# --- writer --------------------------------------------------------------------------------


def test_part_file_positioned_writes(tmp_path: Path) -> None:
    path = tmp_path / "a.bin.odm-part"
    part = PartFile(path)
    part.open(create=True)
    part.preallocate(20)
    assert path.stat().st_size == 20
    part.write_at(10, b"0123456789")
    part.write_at(0, b"abcdefghij")
    part.sync()
    part.close()
    assert path.read_bytes() == b"abcdefghij0123456789"
    part.open(create=False)
    part.write_at(5, b"XY")
    part.close()
    assert path.read_bytes() == b"abcdeXYhij0123456789"


def test_part_file_truncate(tmp_path: Path) -> None:
    path = tmp_path / "p"
    part = PartFile(path)
    part.open(create=True)
    part.write_at(0, b"abcdef")
    part.truncate(2)
    part.close()
    assert path.read_bytes() == b"ab"
