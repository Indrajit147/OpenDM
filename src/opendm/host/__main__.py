"""opendm-host: the Native Messaging host started by Chrome/Edge (spec 6.6).

Reads one message from stdin, replies on stdout, exits. Chrome only lets the extensions
listed in the host manifest's ``allowed_origins`` start it (and passes the extension's origin
as the first argument).

``--register`` / ``--unregister`` / ``--status`` set up Chrome and Edge for this copy of OpenDM
(used by the portable build).
"""

import os
import sys

from opendm.host.protocol import BrowserMessageError, read_message, write_message
from opendm.host.relay import handle


def _binary_stdio() -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def _setup(command: str) -> int:
    from opendm.host import register as reg

    if command == "--status":
        for browser, manifest in reg.status().items():
            state = f"registered ({manifest})" if manifest else "not registered"
            print(f"{browser}: {state}")
        return 0
    host, folder = reg.registration_target()
    if command == "--register":
        manifest = reg.register(host, folder)
        print(f"Registered for {', '.join(reg.BROWSERS)}: {manifest}")
    else:
        reg.unregister(manifest_dir=folder)
        print(f"Unregistered from {', '.join(reg.BROWSERS)}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("--register", "--unregister", "--status"):
        return _setup(args[0])
    _binary_stdio()
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    try:
        message = read_message(stdin)
    except BrowserMessageError as exc:
        write_message(stdout, {"ok": False, "error": "invalid", "message": str(exc)})
        return 1
    if message is None:
        return 0
    write_message(stdout, handle(message))
    return 0


if __name__ == "__main__":
    sys.exit(main())
