import random

import pytest

from opendm.engine.http.planner import Segment, plan_segments, split_largest

MIB = 1024 * 1024


def assert_tiles(segments: list[Segment], size: int) -> None:
    """Segments are sorted, contiguous, non-overlapping and cover [0, size)."""
    pos = 0
    for seg in segments:
        assert seg.start == pos
        assert seg.end is not None and seg.end > seg.start
        assert 0 <= seg.written <= seg.received <= seg.end - seg.start
        pos = seg.end
    assert pos == size


@pytest.mark.parametrize(
    ("size", "n", "count"),
    [
        (100 * MIB, 8, 8),
        (8 * MIB, 8, 8),
        (5 * MIB, 8, 5),  # minimum segment of 1 MiB limits the count
        (MIB // 2, 8, 1),
        (100 * MIB + 7, 8, 8),  # remainder goes to the last segment
        (10 * MIB, 1, 1),
    ],
)
def test_plan_segments(size: int, n: int, count: int) -> None:
    segments = plan_segments(size, n, MIB)
    assert len(segments) == count
    assert_tiles(segments, size)


def test_plan_empty_file() -> None:
    segments = plan_segments(0, 8, MIB)
    assert len(segments) == 1 and segments[0].complete


def test_segment_properties() -> None:
    seg = Segment(100, 200, received=30, written=20)
    assert seg.pos == 130
    assert seg.remaining == 70
    assert not seg.complete
    seg.received = 100
    assert seg.complete
    assert Segment(0, None).remaining is None


def test_split_largest_takes_second_half_of_remaining() -> None:
    segments = plan_segments(8 * MIB, 2, MIB)  # [0,4M) [4M,8M)
    segments[0].received = segments[0].written = 4 * MIB  # first one finished
    segments[1].received = segments[1].written = MIB
    new = split_largest(segments, MIB)
    assert new is not None
    assert segments[1].end == new.start == 4 * MIB + MIB + (3 * MIB) // 2
    assert new.end == 8 * MIB
    assert_tiles(segments, 8 * MIB)
    assert new in segments


def test_split_refuses_small_remainders() -> None:
    segments = plan_segments(3 * MIB, 1, MIB)
    segments[0].received = 2 * MIB  # 1 MiB left < 2 * min_segment
    assert split_largest(segments, MIB) is None


def test_split_ignores_unknown_size() -> None:
    assert split_largest([Segment(0, None)], MIB) is None


def test_random_progress_and_splits_keep_tiling() -> None:
    rng = random.Random(1234)
    for _ in range(200):
        size = rng.randint(1, 50) * MIB + rng.randint(0, MIB)
        min_seg = rng.choice([64 * 1024, 256 * 1024, MIB])
        segments = plan_segments(size, rng.randint(1, 32), min_seg)
        for _ in range(rng.randint(0, 40)):
            seg = rng.choice(segments)
            assert seg.end is not None
            seg.received = rng.randint(seg.received, seg.end - seg.start)
            seg.written = rng.randint(seg.written, seg.received)
            split_largest(segments, min_seg)
            assert_tiles(segments, size)
