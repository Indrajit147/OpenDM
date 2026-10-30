"""Split a file into byte ranges for parallel connections, and re-split as they finish."""

import bisect
from dataclasses import dataclass


@dataclass
class Segment:
    """Byte range ``[start, end)`` of the target file; ``end`` is None if size is unknown.

    ``received`` counts bytes taken from the network (some may still be buffered),
    ``written`` counts bytes handed to the file. Only ``written`` is checkpointed.
    """

    start: int
    end: int | None
    received: int = 0
    written: int = 0

    @property
    def pos(self) -> int:
        return self.start + self.received

    @property
    def remaining(self) -> int | None:
        return None if self.end is None else max(self.end - self.pos, 0)

    @property
    def complete(self) -> bool:
        return self.end is not None and self.pos >= self.end

    def __lt__(self, other: "Segment") -> bool:
        return self.start < other.start


def plan_segments(size: int, connections: int, min_segment: int) -> list[Segment]:
    """Equal ranges, at most ``connections`` of them, none smaller than ``min_segment``."""
    count = max(1, min(connections, size // max(min_segment, 1)))
    step = size // count
    bounds = [i * step for i in range(count)] + [size]
    return [Segment(bounds[i], bounds[i + 1]) for i in range(count)]


def split_largest(segments: list[Segment], min_segment: int) -> Segment | None:
    """Give the second half of the largest remaining range to a new segment.

    The split segment keeps downloading up to its new, smaller ``end``. Returns
    None when no segment has at least ``2 * min_segment`` bytes left.
    """
    candidates = [s for s in segments if s.remaining is not None]
    if not candidates:
        return None
    largest = max(candidates, key=lambda s: s.remaining or 0)
    remaining = largest.remaining or 0
    if remaining < 2 * min_segment:
        return None
    assert largest.end is not None
    mid = largest.pos + remaining // 2
    new = Segment(mid, largest.end)
    largest.end = mid
    bisect.insort(segments, new)
    return new
