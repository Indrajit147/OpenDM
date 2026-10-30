"""Sleep and shutdown for after-queue actions. Only called after the 60 s countdown."""

import subprocess
import sys

from opendm.core.models import AfterAction


def perform_power(action: AfterAction) -> None:
    if sys.platform != "win32" or action is AfterAction.NONE:
        return
    if action is AfterAction.SHUTDOWN:
        # No shell; argument list only (spec 7).
        subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
    elif action is AfterAction.SLEEP:
        import ctypes

        # SetSuspendState(hibernate=False, force=False, wakeup_events_disabled=False)
        ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)
