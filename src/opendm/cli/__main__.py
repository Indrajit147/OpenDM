"""opendm-cli: command-line interface.

Until the app and its IPC exist (M4), only ``get --standalone`` works: it runs the
engine in this process. Exit codes: 0 done, 1 download failed, 2 usage error,
130 interrupted (Ctrl+C).
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from opendm import __version__
from opendm.core.branding import APP_NAME
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.events import Event, Failed, Progress
from opendm.core.models import DownloadRequest
from opendm.core.units import format_bytes, format_duration
from opendm.engine.http.single import SingleStreamDownload

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
_USAGE_KINDS = frozenset({ErrorKind.INVALID_URL, ErrorKind.UNSUPPORTED_SCHEME})


def parse_header(text: str) -> tuple[str, str]:
    """``"Name: value"`` -> ("Name", "value")."""
    name, sep, value = text.partition(":")
    if not sep or not name.strip():
        raise ValueError(f"expected 'Name: value', got {text!r}")
    return name.strip(), value.strip()


def _header_arg(text: str) -> tuple[str, str]:
    try:
        return parse_header(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opendm-cli", description=f"{APP_NAME} command line")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    get = sub.add_parser("get", help="download a URL")
    get.add_argument("url")
    get.add_argument(
        "-o", "--output-dir", type=Path, default=None, help="folder (default: current)"
    )
    get.add_argument("-n", "--name", help="file name (default: detected from the server)")
    get.add_argument("-c", "--connections", type=int, default=1, help="connections (M2)")
    get.add_argument("--header", type=_header_arg, action="append", default=[], metavar="'K: V'")
    get.add_argument("--user-agent")
    get.add_argument("--referer")
    get.add_argument("--cookie", help="Cookie header value")
    get.add_argument("--insecure", action="store_true", help="skip TLS certificate checks")
    get.add_argument("--media", action="store_true", help="download via yt-dlp (M5)")
    get.add_argument("--standalone", action="store_true", help="run without the OpenDM app")
    get.add_argument("-q", "--quiet", action="store_true", help="no progress display")

    sub.add_parser("list", help="list downloads in the running app")
    for name in ("pause", "resume", "remove"):
        sub.add_parser(name, help=f"{name} a download in the running app").add_argument("id")
    return parser


class ConsoleProgress:
    """Renders events as one updating line (only on an interactive terminal)."""

    def __init__(self, stream: TextIO, enabled: bool) -> None:
        self._stream = stream
        self._enabled = enabled
        self._width = 0

    def __call__(self, event: Event) -> None:
        if not self._enabled or not isinstance(event, Progress):
            return
        done = format_bytes(event.downloaded)
        speed = f"{format_bytes(event.speed)}/s"
        if event.total:
            pct = 100 * event.downloaded / event.total
            line = f"{pct:5.1f}%  {done} / {format_bytes(event.total)}  {speed}  "
            line += f"ETA {format_duration(event.eta)}"
        else:
            line = f"{done}  {speed}"
        self._stream.write("\r" + line.ljust(self._width))
        self._width = len(line)
        self._stream.flush()

    def close(self) -> None:
        if self._enabled and self._width:
            self._stream.write("\n")
            self._stream.flush()


def _not_available(command: str) -> int:
    print(
        f"error: '{command}' needs the running OpenDM app, which arrives in milestone M4.",
        file=sys.stderr,
    )
    return EXIT_USAGE


async def _get(args: argparse.Namespace) -> int:
    request = DownloadRequest(
        url=args.url,
        dest_dir=args.output_dir or Path.cwd(),
        filename=args.name,
        headers=dict(args.header),
        user_agent=args.user_agent,
        referrer=args.referer,
        cookies=args.cookie,
        verify_tls=not args.insecure,
    )
    show = not args.quiet and sys.stderr.isatty()
    progress = ConsoleProgress(sys.stderr, enabled=show)
    failed: list[Failed] = []

    def sink(event: Event) -> None:
        if isinstance(event, Failed):
            failed.append(event)
        progress(event)

    download = SingleStreamDownload(request, sink=sink)
    try:
        result = await download.run()
    except asyncio.CancelledError:
        download.cancel()  # Ctrl+C: delete the partial file (decision M1-2)
        raise
    except DownloadError as exc:
        progress.close()
        print(f"error: {exc.message} [{exc.kind}]", file=sys.stderr)
        if failed and failed[0].partial_path:
            print(f"partial file kept: {failed[0].partial_path}", file=sys.stderr)
        return EXIT_USAGE if exc.kind in _USAGE_KINDS else EXIT_FAILED
    progress.close()
    if result is None:
        return EXIT_INTERRUPTED
    print(f"Saved:   {result.path}")
    print(f"Size:    {format_bytes(result.size)} ({result.size} bytes)")
    print(f"SHA-256: {result.sha256}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # non-UTF-8 consoles and pipes
    args = build_parser().parse_args(argv)
    if args.command != "get":
        return _not_available(args.command)
    if not args.standalone:
        print(
            "error: talking to the running OpenDM app arrives in milestone M4; "
            "add --standalone to download in this window.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.media:
        print("error: --media (yt-dlp) arrives in milestone M5.", file=sys.stderr)
        return EXIT_USAGE
    if args.connections != 1:
        print("note: multi-connection downloads arrive in M2; using 1 connection.", file=sys.stderr)
    try:
        return asyncio.run(_get(args))
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
