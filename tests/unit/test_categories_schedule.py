"""Category matching and queue schedule windows."""

from datetime import datetime
from pathlib import Path

import pytest

from opendm.core.models import Category, Queue
from opendm.discovery.categories import category_folder, match_category
from opendm.queue.schedule import in_window

CATS = [
    Category("Video", ("mp4", "mkv", "ts"), "Video", id=1),
    Category("Compressed", ("zip", "gz", "tar.gz", "7z"), "Compressed", id=2),
    Category("Archives", ("tar.gz",), "E:/Archives", id=3),
    Category("Other", (), "", fallback=True, id=4),
]


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("holiday.MP4", "Video"),
        ("movie.final.mkv", "Video"),
        ("data.zip", "Compressed"),
        ("logs.gz", "Compressed"),
        ("src.tar.gz", "Compressed"),  # first category wins a tie on the same extension
        ("readme", "Other"),
        ("noext.", "Other"),
        ("weird.unknownext", "Other"),
        ("", "Other"),
    ],
)
def test_match_category(name: str, category: str) -> None:
    assert match_category(name, CATS).name == category


def test_longest_extension_wins() -> None:
    cats = [Category("GZ", ("gz",), id=1), Category("TGZ", ("tar.gz",), id=2), CATS[-1]]
    assert match_category("x.tar.gz", cats).name == "TGZ"
    assert match_category("x.gz", cats).name == "GZ"


def test_match_without_fallback_uses_last_category() -> None:
    cats = [Category("Video", ("mp4",), id=1)]
    assert match_category("a.zip", cats).name == "Video"


def test_category_folder() -> None:
    base = Path("D:/Downloads")
    assert category_folder(CATS[0], base) == base / "Video"
    assert category_folder(CATS[2], base) == Path("E:/Archives")
    assert category_folder(CATS[3], base) == base


# --- schedule windows ------------------------------------------------------------------------

MON = datetime(2026, 11, 2)  # a Monday
WEEKDAYS = 0b0011111


def at(day_offset: int, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return MON.replace(day=MON.day + day_offset, hour=h, minute=m)


@pytest.mark.parametrize(
    ("when", "inside"),
    [
        (at(0, "00:59"), False),
        (at(0, "01:00"), True),  # start is inclusive
        (at(0, "05:59"), True),
        (at(0, "06:00"), False),  # stop is exclusive
        (at(5, "02:00"), False),  # Saturday is not in the mask
    ],
)
def test_daytime_window(when: datetime, inside: bool) -> None:
    queue = Queue("Night", start_time="01:00", stop_time="06:00", days=WEEKDAYS)
    assert in_window(queue, when) is inside


@pytest.mark.parametrize(
    ("when", "inside"),
    [
        (at(0, "21:59"), False),
        (at(0, "22:00"), True),
        (at(1, "05:59"), True),  # Tuesday morning belongs to Monday's window
        (at(1, "06:00"), False),
        (at(5, "23:00"), False),  # Saturday night: not in the mask
        (at(6, "03:00"), False),  # Sunday morning: Saturday's window, not in the mask
        (at(0, "03:00"), False),  # Monday morning: Sunday's window, not in the mask
    ],
)
def test_overnight_window(when: datetime, inside: bool) -> None:
    queue = Queue("Night", start_time="22:00", stop_time="06:00", days=WEEKDAYS)
    assert in_window(queue, when) is inside


def test_window_without_stop_time_runs_until_midnight() -> None:
    queue = Queue("Evening", start_time="20:00")
    assert not in_window(queue, at(0, "19:59"))
    assert in_window(queue, at(0, "23:59"))


def test_unscheduled_or_disabled_queue_is_never_in_window() -> None:
    assert not in_window(Queue("Main"), at(0, "12:00"))
    disabled = Queue("Off", start_time="00:00", stop_time="23:59", enabled=False)
    assert not in_window(disabled, at(0, "12:00"))
