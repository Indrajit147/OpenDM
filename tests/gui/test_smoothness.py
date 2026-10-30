"""M4 acceptance: the UI stays smooth with 10 parallel downloads."""

import dataclasses
import itertools
import time

from PySide6.QtCore import QTimer

from opendm.core.models import JobState
from tests.gui.conftest import GuiApp
from tests.server.app import FaultServer

DOWNLOADS = 10
MAX_STALL = 0.100  # longest acceptable gap between 10 ms heartbeats, in seconds


def test_ten_parallel_downloads_keep_the_ui_responsive(
    qtbot, gui: GuiApp, server: FaultServer
) -> None:
    gui.save_settings(dataclasses.replace(gui.settings, connections=2, per_host=32))
    # Raise Main's concurrency so all ten run at once.
    gui.engine.call(
        lambda m: m.queues.save(dataclasses.replace(m.queues.get(1), max_concurrent=10))
    ).result(5)
    urls = [server.url(f"/file/p{i}.bin?size=3M&rate=512K") for i in range(DOWNLOADS)]
    gui.window.add_urls(urls, ask=False)

    beats: list[float] = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(time.perf_counter()))
    qtbot.waitUntil(
        lambda: sum(j.state is JobState.DOWNLOADING for j in gui.window.model.jobs()) == DOWNLOADS,
        timeout=20_000,
    )
    gui.window.model.progress_updates = 0
    timer.start()
    measure_from = time.perf_counter()
    qtbot.wait(3000)  # all ten downloading for ~3 s (each needs ~3 s at 2 x 512 KiB/s)
    timer.stop()
    elapsed = time.perf_counter() - measure_from
    updates = gui.window.model.progress_updates

    gaps = [b - a for a, b in itertools.pairwise(beats)]
    assert len(beats) > 100
    assert max(gaps) < MAX_STALL, f"UI stalled for {max(gaps) * 1000:.0f} ms"
    per_row_rate = updates / DOWNLOADS / elapsed
    assert 2 <= per_row_rate <= 5, f"{per_row_rate:.1f} table updates per row per second"
    qtbot.waitUntil(
        lambda: all(j.state is JobState.COMPLETED for j in gui.window.model.jobs()),
        timeout=30_000,
    )
