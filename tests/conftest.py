import os
import uuid
from collections.abc import Iterator
from pathlib import Path

# GUI tests run without a visible window (also on CI); set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never talk to (or impersonate) a real OpenDM app running for this user.
os.environ["OPENDM_IPC_NAME"] = f"opendm-tests-{uuid.uuid4().hex[:8]}"

import pytest

from tests.server.app import FaultServer


def pytest_configure(config: pytest.Config) -> None:
    # --basetemp (build/pytest-tmp, see pyproject.toml) needs its parent to exist,
    # which is not the case on a fresh checkout.
    basetemp = config.option.basetemp
    if basetemp:
        Path(basetemp).resolve().parent.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def _fault_server() -> Iterator[FaultServer]:
    with FaultServer() as srv:
        yield srv


@pytest.fixture
def server(_fault_server: FaultServer) -> FaultServer:
    """The shared local test server, with per-resource fault state cleared."""
    _fault_server.reset()
    return _fault_server
