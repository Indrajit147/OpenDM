"""opendm-host: the Native Messaging host started by Chrome/Edge (spec 6.6).

Reads one message from stdin, replies on stdout, exits. Chrome only lets the extensions
listed in the host manifest's ``allowed_origins`` start it.
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


def main() -> int:
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
