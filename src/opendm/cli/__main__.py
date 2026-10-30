"""opendm-cli: command-line interface.

Until the app and its IPC exist (M4), only ``get --standalone`` works: it runs the
engine in this process. Exit codes: 0 done, 1 download failed, 2 usage error,
130 interrupted (Ctrl+C pauses; run the same command again to resume).
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from opendm import __version__
from opendm.core.branding import APP_NAME
from opendm.core.checksum import parse_checksum
from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.events import Event, Failed, Progress
from opendm.core.models import DownloadRequest
from opendm.core.paths import app_data_dir, default_exe_dir
from opendm.core.settings import MAX_CONNECTIONS, EngineSettings
from opendm.core.units import format_bytes, format_duration, parse_size
from opendm.discovery.classify import parse_quality
from opendm.engine.http.download import HttpDownload
from opendm.engine.media.download import MediaDownload
from opendm.engine.media.formats import CONTAINERS, MediaOptions
from opendm.engine.media.ytdlp import ToolPaths
from opendm.ipc import client as ipc_client
from opendm.tools.manager import ToolManager

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
_USAGE_KINDS = frozenset({ErrorKind.INVALID_URL, ErrorKind.UNSUPPORTED_SCHEME})
_HINTS = {
    ErrorKind.VALIDATOR_CHANGED: "add --restart to download the new version from the beginning",
    ErrorKind.LINK_EXPIRED: "get a fresh link and run: opendm-cli get NEW_URL --continue {part}",
}


def parse_header(text: str) -> tuple[str, str]:
    """``"Name: value"`` -> ("Name", "value")."""
    name, sep, value = text.partition(":")
    if not sep or not name.strip():
        raise ValueError(f"expected 'Name: value', got {text!r}")
    return name.strip(), value.strip()


def _arg(parse):  # type: ignore[no-untyped-def]
    """Adapt a ValueError-raising parser for argparse."""

    def convert(text: str):  # type: ignore[no-untyped-def]
        try:
            return parse(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc

    return convert


def _connections(text: str) -> int:
    n = int(text)
    if not 1 <= n <= MAX_CONNECTIONS:
        raise ValueError(f"connections must be 1-{MAX_CONNECTIONS}")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opendm-cli", description=f"{APP_NAME} command line")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    get = sub.add_parser("get", help="download a URL")
    get.add_argument("url")
    get.add_argument("-o", "--output-dir", type=Path, help="folder (default: current)")
    get.add_argument("-n", "--name", help="file name (default: detected from the server)")
    get.add_argument(
        "-c", "--connections", type=_arg(_connections), default=8, help="1-32 (default 8)"
    )
    get.add_argument("--limit", type=_arg(parse_size), help="speed limit, e.g. 500K or 2M")
    sums = get.add_mutually_exclusive_group()
    for algo in ("sha256", "sha1", "md5"):
        sums.add_argument(f"--{algo}", metavar="HEX", help=f"verify the {algo.upper()} checksum")
    get.add_argument("--restart", action="store_true", help="discard a partial download")
    get.add_argument(
        "--continue", dest="part_file", type=Path, metavar="FILE.odm-part",
        help="continue this partial download from URL (e.g. a refreshed link)",
    )  # fmt: skip
    get.add_argument(
        "--header", type=_arg(parse_header), action="append", default=[], metavar="'K: V'"
    )
    get.add_argument("--user-agent")
    get.add_argument("--referer")
    get.add_argument("--cookie", help="Cookie header value")
    get.add_argument("--insecure", action="store_true", help="skip TLS certificate checks")
    get.add_argument("--media", action="store_true", help="video/audio from a web page (yt-dlp)")
    get.add_argument(
        "--quality", type=_arg(parse_quality), default="best",
        help="with --media: best, 2160p...360p, mp3 or m4a (default best)",
    )  # fmt: skip
    get.add_argument("--container", choices=CONTAINERS, default="mp4", help="with --media")
    get.add_argument(
        "--tools-dir", type=Path, help="with --media --standalone: folder with yt-dlp and ffmpeg"
    )
    get.add_argument("--standalone", action="store_true", help="run without the OpenDM app")
    get.add_argument("-q", "--quiet", action="store_true", help="no progress display")

    sub.add_parser("list", help="list downloads in the running app")
    for name in ("pause", "resume", "remove"):
        cmd = sub.add_parser(name, help=f"{name} a download in the running app")
        cmd.add_argument("id")
        if name == "remove":
            cmd.add_argument("--delete-file", action="store_true", help="also delete the file")
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
        conns = f"{event.connections} conn"
        if event.total:
            pct = 100 * event.downloaded / event.total
            line = f"{pct:5.1f}%  {done} / {format_bytes(event.total)}  {speed}  {conns}  "
            line += f"ETA {format_duration(event.eta)}"
        else:
            line = f"{done}  {speed}  {conns}"
        self._stream.write("\r" + line.ljust(self._width))
        self._width = len(line)
        self._stream.flush()

    def close(self) -> None:
        if self._enabled and self._width:
            self._stream.write("\n")
            self._stream.flush()
            self._width = 0


_STANDALONE_ONLY = ("restart", "part_file", "insecure")


def _media_options(args: argparse.Namespace) -> MediaOptions:
    return MediaOptions(quality=args.quality, container=args.container)


def media_tools(folder: Path | None) -> ToolPaths:
    """yt-dlp and FFmpeg for standalone media downloads.

    ``--tools-dir`` wins; otherwise the app's default tools folder is used.
    """
    base = folder or app_data_dir(default_exe_dir()) / "tools"
    return ToolManager(base).paths()


def _ipc(cmd: str, args: dict[str, object] | None = None) -> object:
    """One request to the running app; raises SystemExit with a message on failure."""
    try:
        return ipc_client.request(cmd, args)
    except ipc_client.AppNotRunning:
        print(
            "error: OpenDM is not running. Start the app, or add --standalone to "
            "download in this window.",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_FAILED) from None
    except ipc_client.IpcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_FAILED) from None


def _app_get(args: argparse.Namespace, checksum: str | None) -> int:
    used = [o for o in _STANDALONE_ONLY if getattr(args, o)]
    if used:
        flags = ", ".join("--" + o.replace("part_file", "continue") for o in used)
        print(f"error: {flags} only work with --standalone", file=sys.stderr)
        return EXIT_USAGE
    request: dict[str, object] = {"url": args.url, "connections": args.connections}
    optional = {
        "dest_dir": str(args.output_dir.resolve()) if args.output_dir else None,
        "filename": args.name, "speed_limit": args.limit, "checksum": checksum,
        "referrer": args.referer, "user_agent": args.user_agent, "cookies": args.cookie,
        "headers": dict(args.header) or None,
    }  # fmt: skip
    request.update({k: v for k, v in optional.items() if v is not None})
    if args.media:
        request["media"] = _media_options(args).to_dict()
    try:
        job = _ipc("add", request)
    except SystemExit as exc:
        return int(exc.code or EXIT_FAILED)
    assert isinstance(job, dict)
    print(f"Added {job['id']}: {job['name']}")
    return EXIT_OK


def _app_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "list":
            jobs = _ipc("list")
            assert isinstance(jobs, list)
            for job in jobs:
                size = format_bytes(job["size"]) if job["size"] is not None else "?"
                pct = f"{100 * job['downloaded'] / job['size']:5.1f}%" if job["size"] else "    -"
                print(f"{job['id']}  {job['state']:<11} {pct}  {size:>10}  {job['name']}")
            if not jobs:
                print("no downloads")
            return EXIT_OK
        payload: dict[str, object] = {"job_id": args.id}
        if args.command == "remove" and args.delete_file:
            payload["delete_file"] = True
        _ipc(args.command, payload)
    except SystemExit as exc:
        return int(exc.code or EXIT_FAILED)
    print(f"{args.command}: {args.id}")
    return EXIT_OK


def _checksum(args: argparse.Namespace) -> str | None:
    for algo in ("sha256", "sha1", "md5"):
        value = getattr(args, algo)
        if value:
            return f"{algo}:{value}"
    return None


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
        checksum=_checksum(args),
        speed_limit=args.limit,
        restart=args.restart,
        part_file=args.part_file,
    )
    show = not args.quiet and sys.stderr.isatty()
    progress = ConsoleProgress(sys.stderr, enabled=show)
    failed: list[Failed] = []

    def sink(event: Event) -> None:
        if isinstance(event, Failed):
            failed.append(event)
        progress(event)

    settings = EngineSettings(connections=args.connections)
    download: HttpDownload | MediaDownload
    if args.media:
        data_dir = app_data_dir(default_exe_dir())
        download = MediaDownload(
            request, _media_options(args), tools=media_tools(args.tools_dir),
            temp_dir=data_dir / "tmp", settings=settings, sink=sink,
        )  # fmt: skip
    else:
        download = HttpDownload(request, settings=settings, sink=sink)
    try:
        result = await download.run()
    except asyncio.CancelledError:
        progress.close()
        raise  # the engine already saved a checkpoint and marked the job paused
    except DownloadError as exc:
        progress.close()
        print(f"error: {exc.message} [{exc.kind}]", file=sys.stderr)
        part = failed[0].partial_path if failed else None
        if part:
            print(f"partial file kept: {part}", file=sys.stderr)
        hint = _HINTS.get(exc.kind)
        if hint:
            print(f"hint: {hint.format(part=part or 'FILE.odm-part')}", file=sys.stderr)
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "get":
        return _app_command(args)
    if args.media and (args.restart or args.part_file or _checksum(args)):
        print("error: --restart, --continue and checksums do not apply to --media",
              file=sys.stderr)  # fmt: skip
        return EXIT_USAGE
    checksum = _checksum(args)
    if checksum:
        try:
            parse_checksum(checksum)
        except ValueError as exc:
            parser.error(str(exc))
    if not args.standalone:
        return _app_get(args, checksum)
    try:
        return asyncio.run(_get(args))
    except KeyboardInterrupt:
        print("\npaused - run the same command again to resume", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
