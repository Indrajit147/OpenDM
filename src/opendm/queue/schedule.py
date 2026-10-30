"""Queue schedule windows: start/stop time (local) and days of the week."""

from datetime import datetime, time, timedelta

from opendm.core.models import Queue


def parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _day_enabled(queue: Queue, day: datetime) -> bool:
    return bool(queue.days >> day.weekday() & 1)


def in_window(queue: Queue, now: datetime) -> bool:
    """Whether ``now`` falls inside the queue's schedule window.

    The start time is inclusive and the stop time exclusive. A window whose stop is
    earlier than its start runs overnight; the morning part belongs to the day the
    window started, so the day mask is checked against that day. Without a stop time
    the window lasts until midnight.
    """
    if not queue.scheduled or queue.start_time is None:
        return False
    start = parse_hhmm(queue.start_time)
    stop = parse_hhmm(queue.stop_time) if queue.stop_time else None
    t = now.time()
    if stop is None:
        return t >= start and _day_enabled(queue, now)
    if start < stop:
        return start <= t < stop and _day_enabled(queue, now)
    yesterday = now - timedelta(days=1)
    return (t >= start and _day_enabled(queue, now)) or (
        t < stop and _day_enabled(queue, yesterday)
    )
