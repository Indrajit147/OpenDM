"""Table model, filter, widgets, theme and icon."""

from pathlib import Path

from opendm.core.events import Progress
from opendm.core.models import DownloadRequest, Job, JobState
from opendm.gui.icons import app_icon
from opendm.gui.models.downloads import (
    ETA,
    NAME,
    PROGRESS,
    PROGRESS_ROLE,
    SIZE,
    SPEED,
    STATUS,
    DownloadsFilter,
    DownloadsModel,
    status_text,
)
from opendm.gui.theme import effective_theme
from opendm.gui.widgets.segment_map import SegmentMap
from opendm.gui.widgets.speed_graph import SAMPLES, SpeedGraph


def job(name: str, **kwargs: object) -> Job:
    return Job(DownloadRequest(f"http://h/{name}?token=x", Path("D:/dl")), **kwargs)  # type: ignore[arg-type]


def test_model_rows_and_progress(qtbot) -> None:
    model = DownloadsModel()
    a = job("a.zip", size=1000, state=JobState.DOWNLOADING)
    model.set_jobs([a])
    index = model.index(0, NAME)
    assert model.data(index) == "a.zip"  # no query string
    model.update_progress(Progress(a.id, 250, 1000, 2048.0, 3.0, 4, ()))
    assert model.data(model.index(0, PROGRESS)) == "25.0%"
    assert model.data(model.index(0, PROGRESS), PROGRESS_ROLE) == 0.25
    assert model.data(model.index(0, SPEED)) == "2.0 KiB/s"
    assert model.data(model.index(0, ETA)) == "0:03"
    assert model.data(model.index(0, SIZE)) == "1000 B"
    assert model.progress_updates == 1


def test_model_update_insert_remove(qtbot) -> None:
    model = DownloadsModel()
    a = job("a.zip", state=JobState.DOWNLOADING, size=100, downloaded=10)
    model.update_job(a)
    model.update_progress(Progress(a.id, 80, 100, 10.0, 2.0))
    stale = job("a.zip", state=JobState.DOWNLOADING, size=100, downloaded=40)
    stale.id = a.id
    model.update_job(stale)  # a lagging snapshot never moves progress backwards
    assert model.job(a.id).downloaded == 80  # type: ignore[union-attr]
    done = job("a.zip", state=JobState.COMPLETED, size=100, downloaded=100)
    done.id = a.id
    model.update_job(done)
    assert model.data(model.index(0, SPEED)) == ""
    assert model.rowCount() == 1
    model.remove_job(a.id)
    assert model.rowCount() == 0
    model.update_progress(Progress("unknown", 1, 1, 1.0, None))  # ignored


def test_status_text() -> None:
    assert (
        status_text(job("a", state=JobState.PAUSED, message="interrupted"))
        == "Paused (interrupted)"
    )
    failed = job("a", state=JobState.FAILED, error_message="server replied HTTP 404")
    assert status_text(failed) == "Failed: server replied HTTP 404"
    assert status_text(job("a", state=JobState.COMPLETED)) == "Completed"


def test_filter_views_and_search(qtbot) -> None:
    model = DownloadsModel()
    model.set_jobs([
        job("movie.mkv", category_id=1, queue_id=1, state=JobState.COMPLETED),
        job("report.pdf", category_id=3, queue_id=2),
        job("song.mp3", category_id=2, queue_id=1, state=JobState.PAUSED),
    ])  # fmt: skip
    proxy = DownloadsFilter()
    proxy.setSourceModel(model)

    def names() -> list[str]:
        return sorted(proxy.data(proxy.index(r, NAME)) for r in range(proxy.rowCount()))

    assert len(names()) == 3
    proxy.set_view("finished")
    assert names() == ["movie.mkv"]
    proxy.set_view("unfinished")
    assert names() == ["report.pdf", "song.mp3"]
    proxy.set_view("category", 3)
    assert names() == ["report.pdf"]
    proxy.set_view("queue", 1)
    assert names() == ["movie.mkv", "song.mp3"]
    proxy.set_view("all")
    proxy.set_search("SONG")
    assert names() == ["song.mp3"]


def test_sorting_by_size(qtbot) -> None:
    model = DownloadsModel()
    model.set_jobs([job("big", size=5000), job("small", size=10), job("unknown")])
    proxy = DownloadsFilter()
    proxy.setSourceModel(model)
    proxy.sort(SIZE)
    assert [proxy.data(proxy.index(r, NAME)) for r in range(3)] == ["unknown", "small", "big"]
    assert proxy.data(proxy.index(0, STATUS)) == "Queued"


def test_segment_map(qtbot) -> None:
    widget = SegmentMap()
    qtbot.addWidget(widget)
    widget.set_data(1000, [(0, 500, 250), (500, 1000, 250)])
    assert widget.filled_fraction() == 0.5
    widget.resize(300, 30)
    widget.grab()  # paints without errors
    widget.set_data(None, [(0, None, 10)])
    assert widget.filled_fraction() == 0.0
    widget.grab()
    widget.set_complete(True)
    assert widget.filled_fraction() == 1.0
    widget.grab()


def test_speed_graph_keeps_last_minute(qtbot) -> None:
    graph = SpeedGraph()
    qtbot.addWidget(graph)
    for i in range(100):
        graph.add_sample(float(i))
    assert len(graph.samples) == SAMPLES and graph.samples[-1] == 99.0
    graph.resize(300, 100)
    graph.grab()


def test_theme_choice() -> None:
    assert effective_theme("dark", system_dark=False) == "dark"
    assert effective_theme("light", system_dark=True) == "light"
    assert effective_theme("system", system_dark=True) == "dark"
    assert effective_theme("system", system_dark=False) == "light"


def test_app_icon(qtbot) -> None:
    icon = app_icon()
    assert not icon.isNull()
    assert {s.width() for s in icon.availableSizes()} >= {16, 32, 256}
