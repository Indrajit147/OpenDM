"""Single source of truth for the product name and every identifier derived from it.

Renaming the app should only require editing this file (plus the installer and
extension manifests, which are generated from or checked against these values).
"""

from typing import Final

APP_NAME: Final = "OpenDM"
APP_SLUG: Final = APP_NAME.lower()
APP_DESCRIPTION: Final = "Free, open-source download manager"
REPO_URL: Final = "https://github.com/Indrajit147/OpenDM"

GUI_EXE: Final = f"{APP_NAME}.exe"
CLI_EXE: Final = f"{APP_SLUG}-cli.exe"
HOST_EXE: Final = f"{APP_SLUG}-host.exe"

# Native Messaging host name: lowercase letters, digits, "_" and "." only.
NATIVE_HOST_NAME: Final = f"io.github.indrajit147.{APP_SLUG}"

# Named pipe used for IPC and as the single-instance lock (made per-user at runtime).
PIPE_NAME: Final = f"{APP_SLUG}-ipc"

# On-disk download format (decision D8): "name.ext" + suffix.
PARTIAL_SUFFIX: Final = ".odm-part"
STATE_SUFFIX: Final = ".odm-state"
LOCK_SUFFIX: Final = ".odm-lock"
