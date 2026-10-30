"""Named-pipe IPC server in the GUI process (decision D10).

Restricted to the current Windows user; it doubles as the single-instance lock
(a second ``listen()`` with the same name fails). Handlers run on the GUI thread
and may return a ``concurrent.futures.Future`` (e.g. from the engine bridge); the
reply is sent when it completes, back on the GUI thread.
"""

import concurrent.futures
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from opendm.ipc.protocol import (
    MAX_MESSAGE,
    ProtocolError,
    Request,
    decode_request,
    encode,
    error_response,
    ok_response,
)

Handler = Callable[[Request], Any]


class IpcServer(QObject):
    _reply = Signal(object, object)  # socket, response dict (emitted from any thread)

    def __init__(self, handler: Handler, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._reply.connect(self._send)

    def listen(self, name: str) -> bool:
        """False if another instance already owns the name."""
        return self._server.listen(name)

    def close(self) -> None:
        self._server.close()

    @property
    def name(self) -> str:
        return self._server.serverName()

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _drop(self, sock: QLocalSocket) -> None:
        self._buffers.pop(sock, None)
        sock.deleteLater()

    def _read(self, sock: QLocalSocket) -> None:
        buffer = self._buffers.get(sock)
        if buffer is None:
            return
        buffer += bytes(sock.readAll().data())
        while b"\n" in buffer:
            line, _, rest = bytes(buffer).partition(b"\n")
            buffer[:] = rest
            self._handle(sock, line)
        if len(buffer) > MAX_MESSAGE:
            self._send(sock, error_response("message too large"))
            sock.disconnectFromServer()

    def _handle(self, sock: QLocalSocket, line: bytes) -> None:
        try:
            request = decode_request(line)
            result = self._handler(request)
        except ProtocolError as exc:
            self._send(sock, error_response(str(exc)))
            return
        except Exception as exc:
            self._send(sock, error_response(str(exc) or type(exc).__name__))
            return
        if isinstance(result, concurrent.futures.Future):
            result.add_done_callback(lambda f, s=sock: self._reply.emit(s, _from_future(f)))
        else:
            self._send(sock, ok_response(result))

    def _send(self, sock: QLocalSocket, response: dict[str, Any]) -> None:
        if (
            not shiboken6.isValid(sock)
            or sock.state() != QLocalSocket.LocalSocketState.ConnectedState
        ):
            return
        sock.write(encode(response))
        sock.flush()


def _from_future(future: "concurrent.futures.Future[Any]") -> dict[str, Any]:
    try:
        return ok_response(future.result())
    except Exception as exc:
        return error_response(str(exc) or type(exc).__name__)
