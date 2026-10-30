import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from opendm.core.models import AfterAction
from opendm.core.settings import EngineSettings, RetryPolicy
from opendm.gui.app import Application

FAST = EngineSettings(
    connections=4,
    min_segment=64 * 1024,
    buffer_size=64 * 1024,
    state_interval=0.1,
    progress_interval=0.05,
    retry=RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05, max_retry_after=0.1),
)


class GuiApp(Application):
    power_calls: list[AfterAction]


@pytest.fixture
def gui(qtbot, tmp_path: Path) -> Iterator[GuiApp]:
    calls: list[AfterAction] = []
    qapp = QApplication.instance()
    app = Application(
        qapp,  # type: ignore[arg-type]
        tmp_path / "data",
        downloads=tmp_path / "dl",
        ipc_name=os.environ["OPENDM_IPC_NAME"],
        engine_settings=FAST,
        power=calls.append,
        countdown_seconds=2,
    )
    app.power_calls = calls  # type: ignore[attr-defined]
    app.save_settings(dataclasses.replace(app.settings, first_run_done=True, per_host=32))
    app.start(wizard=False)
    qtbot.waitUntil(lambda: bool(app.window.categories), timeout=5000)
    yield app  # type: ignore[misc]
    app.window.allow_close = True
    app.window.close()
    app.shutdown()
