"""Local HTTP test server with fault injection. Dev-only, standard library only.

Body content is generated deterministically from ``(size, seed)``, so tests can
check SHA-256 without storing files. Faults are query parameters on ``/file/<name>``
and can be combined, e.g. ``/file/big.bin?size=100M&rate=2M&drop_at=5000000``.

Routes
    /file/<name>        the downloadable resource (parameters below)
    /protected/<name>   same as /file, but 403 unless cookie odm_session=opendm-test
    /set-cookie         sets that cookie
    /redirect/<n>       302 chain of n hops, then to ?to=<path> (default /file/redirected.bin);
                        ?code=301|302|303|307|308
    /status/<code>      replies with that HTTP status
    /_reset             clears per-resource fault state

/file parameters
    size=<n>[K|M|G]     body size (default 1M); seed=<int> content seed (default 1)
    type=<mime>         Content-Type (default application/octet-stream)
    range=bytes|none|ignore
                        bytes: honour Range (default); none: no ranges; ignore: advertise
                        Accept-Ranges but always answer 200 (the "200 instead of 206" case)
    length=yes|none|chunked
                        Content-Length (default), close-delimited body, or chunked
    cd=<filename>       send Content-Disposition; cd_mode=both|ext|plain|raw (default both;
                        raw = UTF-8 bytes inside filename="...", as broken servers do)
    rate=<n>[K|M]       throttle to n bytes/s
    slow_start=<sec>    wait before sending the response headers
    drop_at=<offset>    close the connection once the body reaches this file offset
                        (requests that start at or after the offset are not affected)
    etag_after=<n>      after n requests, ETag, Last-Modified and content change
    expire_after=<sec>  403 once this long has passed since the first request
    gzip=1              Content-Encoding: gzip, no ranges
    head=fail|lie|nolength
                        HEAD answers 405 / Content-Length 0 / no Content-Length
    fail_first=<n>      the first n requests (any method) answer 500
    max_conn=<n>        answer 503 + Retry-After while more than n requests are active
    retry_after=<sec>   Retry-After value for max_conn (default 1)

Fault state (request counts, first-request time) is kept per full request path,
so give each test its own path or call ``FaultServer.reset()``. ``FaultServer.stats(path)``
reports requests, GETs, peak parallel requests and body bytes sent for a path.
"""

import argparse
import contextlib
import gzip
import hashlib
import random
import socket
import sys
import threading
import time
from collections.abc import Iterable, Iterator
from email.utils import formatdate, parsedate_to_datetime
from functools import lru_cache
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Self
from urllib.parse import parse_qs, quote, urlencode, urlsplit

CHUNK = 64 * 1024  # content generator block
WRITE_SIZE = 16 * 1024  # socket write size (keeps throttling smooth)
DEFAULT_SIZE = 1024 * 1024
BASE_MTIME = 1_767_225_600  # 2026-01-01T00:00:00Z
COOKIE_NAME = "odm_session"
COOKIE_VALUE = "opendm-test"
_UNITS = {"K": 1024, "M": 1024**2, "G": 1024**3}


class RangeNotSatisfiable(Exception):
    """The Range header is valid but selects no bytes of the resource."""


class BadParameter(Exception):
    """A query parameter could not be parsed."""


# --- deterministic content ----------------------------------------------------


@lru_cache(maxsize=64)
def _block(seed: int, index: int) -> bytes:
    return random.Random(seed * 1_000_003 + index).randbytes(CHUNK)


def content_seed(seed: int, version: int) -> int:
    """Seed of the representation served after ``version`` ETag changes."""
    return seed + version * 7919


def iter_content(size: int, seed: int, start: int = 0, end: int | None = None) -> Iterator[bytes]:
    """Yield bytes ``[start, end)`` of the deterministic body for ``(size, seed)``."""
    end = size if end is None else min(end, size)
    pos = start
    while pos < end:
        index, offset = divmod(pos, CHUNK)
        piece = _block(seed, index)[offset : offset + min(CHUNK - offset, end - pos)]
        yield piece
        pos += len(piece)


def content_bytes(size: int, seed: int, start: int = 0, end: int | None = None) -> bytes:
    return b"".join(iter_content(size, seed, start, end))


@lru_cache(maxsize=32)
def content_sha256(size: int, seed: int) -> str:
    digest = hashlib.sha256()
    for piece in iter_content(size, seed):
        digest.update(piece)
    return digest.hexdigest()


# --- parsing helpers ----------------------------------------------------------------


def parse_size(text: str) -> int:
    """Parse ``123``, ``4K``, ``2M`` or ``1G`` (binary units, case-insensitive)."""
    text = text.strip().upper()
    factor = _UNITS.get(text[-1:], 1)
    if factor != 1:
        text = text[:-1]
    return int(text) * factor


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse a single byte range (RFC 9110 14.1.2) into ``(start, end_exclusive)``.

    Returns None when the header must be ignored (other unit, multiple ranges, bad
    syntax), so the full body is sent. Raises RangeNotSatisfiable for a valid range
    that selects nothing.
    """
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, dash, last = spec.strip().partition("-")
    if not dash:
        return None
    try:
        if first == "":
            suffix = int(last)
            if suffix == 0:
                raise RangeNotSatisfiable
            return max(0, size - suffix), size
        start = int(first)
        end = None if last == "" else int(last) + 1
    except ValueError:
        return None
    if end is not None and end <= start:
        return None  # last-pos < first-pos is invalid syntax
    if start >= size:
        raise RangeNotSatisfiable
    return start, size if end is None else min(end, size)


def content_disposition(name: str, mode: str) -> str:
    """Build a Content-Disposition value (RFC 6266 / RFC 5987) in the given style."""
    ext = f"filename*=UTF-8''{quote(name, safe='')}"
    if mode == "plain":
        return f'attachment; filename="{name}"'
    if mode == "ext":
        return f"attachment; {ext}"
    if mode == "raw":
        # http.server encodes headers as Latin-1; smuggle the UTF-8 bytes through.
        return f'attachment; filename="{name}"'.encode().decode("latin-1")
    fallback = name.encode("ascii", "replace").decode().replace("?", "_")
    return f'attachment; filename="{fallback}"; {ext}'


# --- server state ----------------------------------------------------------------------


class ServerState:
    """Per-resource counters used by stateful faults. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, int] = {}
        self._first: dict[str, float] = {}
        self._stats: dict[str, dict[str, int]] = {}

    def _stat(self, key: str) -> dict[str, int]:
        return self._stats.setdefault(
            key, {"requests": 0, "gets": 0, "active": 0, "peak": 0, "bytes_sent": 0}
        )

    def hit(self, key: str) -> tuple[int, float]:
        """Record a request; return (requests so far including this one, first time)."""
        with self._lock:
            self._hits[key] = self._hits.get(key, 0) + 1
            first = self._first.setdefault(key, time.monotonic())
            return self._hits[key], first

    def enter(self, key: str, method: str) -> int:
        """Mark a request active; return how many are active now (including it)."""
        with self._lock:
            stat = self._stat(key)
            stat["requests"] += 1
            stat["gets"] += method == "GET"
            stat["active"] += 1
            stat["peak"] = max(stat["peak"], stat["active"])
            return stat["active"]

    def leave(self, key: str) -> None:
        with self._lock:
            self._stat(key)["active"] -= 1

    def sent(self, key: str, nbytes: int) -> None:
        with self._lock:
            self._stat(key)["bytes_sent"] += nbytes

    def stats(self, key: str) -> dict[str, int]:
        with self._lock:
            return dict(self._stat(key))

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._first.clear()
            self._stats.clear()


# --- request handler -----------------------------------------------------------------------


class FaultHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: "_Server"

    def log_message(self, format: str, *args: object) -> None:
        if self.server.verbose:
            super().log_message(format, *args)

    def do_GET(self) -> None:
        self._dispatch(head=False)

    def do_HEAD(self) -> None:
        self._dispatch(head=True)

    def _dispatch(self, head: bool) -> None:
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        parts = [p for p in url.path.split("/") if p]
        route = parts[0] if parts else ""
        try:
            if route == "file":
                self._file(query, head)
            elif route == "protected":
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                morsel = cookie.get(COOKIE_NAME)
                if morsel is None or morsel.value != COOKIE_VALUE:
                    self._simple(403, b"cookie required\n")
                else:
                    self._file(query, head)
            elif route == "set-cookie":
                self._simple(200, b"ok\n", {"Set-Cookie": f"{COOKIE_NAME}={COOKIE_VALUE}; Path=/"})
            elif route == "redirect" and len(parts) == 2:
                self._redirect(int(parts[1]), query)
            elif route == "status" and len(parts) == 2:
                self._simple(int(parts[1]), f"status {parts[1]}\n".encode())
            elif route == "_reset":
                self.server.state.reset()
                self._simple(204)
            else:
                self._simple(404, b"not found\n")
        except (BadParameter, ValueError) as exc:
            self._simple(400, f"bad parameter: {exc}\n".encode())
        except ConnectionError:
            self.close_connection = True

    def _simple(self, code: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if code not in (204, 304):
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, hops: int, query: dict[str, str]) -> None:
        target = query.get("to", "/file/redirected.bin")
        code = int(query.get("code", "302"))
        if hops > 1:
            location = f"/redirect/{hops - 1}?" + urlencode({"to": target, "code": code})
        else:
            location = target
        self._simple(code, b"", {"Location": location})

    def _file(self, q: dict[str, str], head: bool) -> None:
        state = self.server.state
        active = state.enter(self.path, self.command)
        try:
            if "max_conn" in q and active > int(q["max_conn"]):
                retry = q.get("retry_after", "1")
                self._simple(503, b"too many connections\n", {"Retry-After": retry})
                return
            self._file_response(q, head)
        finally:
            state.leave(self.path)

    def _file_response(self, q: dict[str, str], head: bool) -> None:
        size = parse_size(q.get("size", str(DEFAULT_SIZE)))
        seed = int(q.get("seed", "1"))
        range_mode = q.get("range", "bytes")
        length_mode = q.get("length", "yes")
        use_gzip = q.get("gzip") == "1"
        rate = parse_size(q["rate"]) if "rate" in q else 0
        drop_at = int(q["drop_at"]) if "drop_at" in q else None
        if range_mode not in ("bytes", "none", "ignore"):
            raise BadParameter("range")
        if length_mode not in ("yes", "none", "chunked"):
            raise BadParameter("length")

        if "slow_start" in q:
            time.sleep(float(q["slow_start"]))
        count, first = self.server.state.hit(self.path)
        if count <= int(q.get("fail_first", "0")):
            self._simple(500, b"injected failure\n")
            return
        if "expire_after" in q and time.monotonic() - first >= float(q["expire_after"]):
            self._simple(403, b"link expired\n")
            return

        version = 1 if "etag_after" in q and count > int(q["etag_after"]) else 0
        cseed = content_seed(seed, version)
        etag = f'"{size:x}-{seed:x}-v{version}"'
        last_modified = formatdate(BASE_MTIME + version * 86_400, usegmt=True)

        if head and q.get("head") == "fail":
            self._simple(405, b"HEAD not allowed\n", {"Allow": "GET"})
            return

        headers = {
            "Content-Type": q.get("type", "application/octet-stream"),
            "ETag": etag,
            "Last-Modified": last_modified,
        }
        if range_mode in ("bytes", "ignore") and not use_gzip:
            headers["Accept-Ranges"] = "bytes"
        if "cd" in q:
            headers["Content-Disposition"] = content_disposition(q["cd"], q.get("cd_mode", "both"))

        status, start, end = 200, 0, size
        range_header = self.headers.get("Range")
        honour_range = range_mode == "bytes" and not use_gzip
        if range_header and honour_range and self._if_range_matches(etag, last_modified):
            try:
                selected = parse_range(range_header, size)
            except RangeNotSatisfiable:
                self._simple(416, b"", {"Content-Range": f"bytes */{size}"})
                return
            if selected is not None:
                status, (start, end) = 206, selected
                headers["Content-Range"] = f"bytes {start}-{end - 1}/{size}"

        body: Iterable[bytes]
        if use_gzip:
            data = gzip.compress(content_bytes(size, cseed), mtime=0)
            headers["Content-Encoding"] = "gzip"
            body, length = [data], len(data)
        else:
            body, length = iter_content(size, cseed, start, end), end - start

        chunked = length_mode == "chunked"
        if head and q.get("head") == "lie":
            headers["Content-Length"] = "0"
            headers.pop("Accept-Ranges", None)
        elif length_mode == "yes" and not (head and q.get("head") == "nolength"):
            headers["Content-Length"] = str(length)
        elif chunked:
            headers["Transfer-Encoding"] = "chunked"
        else:
            headers["Connection"] = "close"
            self.close_connection = True

        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if head:
            return
        self._stream(body, start, chunked, rate, drop_at if not use_gzip else None)

    def _if_range_matches(self, etag: str, last_modified: str) -> bool:
        """RFC 9110 13.1.5: send the range only if the validator is unchanged."""
        value = self.headers.get("If-Range")
        if value is None:
            return True
        value = value.strip()
        if value.startswith(('"', "W/")):
            return value == etag  # strong comparison; weak tags never match
        try:
            return parsedate_to_datetime(value) == parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            return False

    def _stream(
        self, body: Iterable[bytes], pos: int, chunked: bool, rate: int, drop_at: int | None
    ) -> None:
        started, sent = time.monotonic(), 0
        for piece in body:
            for i in range(0, len(piece), WRITE_SIZE):
                part = piece[i : i + WRITE_SIZE]
                drop = drop_at is not None and pos < drop_at <= pos + len(part)
                if drop:
                    part = part[: drop_at - pos]
                self._write(part, chunked)
                if drop:
                    self._drop()
                    return
                pos += len(part)
                sent += len(part)
                if rate:
                    delay = started + sent / rate - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
        if chunked:
            self.wfile.write(b"0\r\n\r\n")

    def _write(self, data: bytes, chunked: bool) -> None:
        if not data:
            return
        if chunked:
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        else:
            self.wfile.write(data)
        self.server.state.sent(self.path, len(data))

    def _drop(self) -> None:
        """End the connection mid-body. FIN (not RST) so the client gets exactly N bytes."""
        self.wfile.flush()
        self.close_connection = True
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows SO_REUSEADDR would let another socket share the port

    def __init__(self, address: tuple[str, int], verbose: bool = False) -> None:
        super().__init__(address, FaultHandler)
        self.state = ServerState()
        self.verbose = verbose

    def handle_error(self, request: object, client_address: object) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            return  # client went away; expected when tests abort downloads
        super().handle_error(request, client_address)  # type: ignore[arg-type]


class FaultServer:
    """Runs the test server on a background thread. Use as a context manager."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, verbose: bool = False) -> None:
        self._httpd = _Server((host, port), verbose)
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return str(self._httpd.server_address[0])

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def url(self, path: str) -> str:
        return self.base_url + path

    def reset(self) -> None:
        self._httpd.state.reset()

    def stats(self, path: str) -> dict[str, int]:
        """requests, gets, active, peak (parallel requests) and bytes_sent for ``path``."""
        return self._httpd.state.stats(path)

    def start(self) -> Self:
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="OpenDM local fault-injection test server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)
    server = FaultServer(args.host, args.port, verbose=args.verbose)
    print(f"Serving on {server.base_url}  (Ctrl+C to stop)")
    print(__doc__)
    try:
        server._httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server._httpd.server_close()


if __name__ == "__main__":
    main()
