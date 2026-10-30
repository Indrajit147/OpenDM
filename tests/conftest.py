from collections.abc import Iterator
from pathlib import Path

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
