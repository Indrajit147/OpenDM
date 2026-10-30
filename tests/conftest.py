from collections.abc import Iterator

import pytest

from tests.server.app import FaultServer


@pytest.fixture(scope="session")
def _fault_server() -> Iterator[FaultServer]:
    with FaultServer() as srv:
        yield srv


@pytest.fixture
def server(_fault_server: FaultServer) -> FaultServer:
    """The shared local test server, with per-resource fault state cleared."""
    _fault_server.reset()
    return _fault_server
