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

# Extensions allowed to start the host: the unpacked one (fixed by the manifest "key") and
# each store's own ID.
EXTENSION_IDS: Final = (
    "pjkejmcidaikllfpgmfginpahcockofb",  # unpacked
    "bionffckkflcblecfgnclbndjflemgld",  # Microsoft Edge Add-ons
)

# Held by the running app so the installer and uninstaller can ask the user to close it
# (Inno Setup AppMutex). Fixed, unlike the per-user pipe name.
APP_MUTEX: Final = f"{APP_NAME}-AppRunning"

# Windows app identity: groups taskbar buttons and names the app in notifications. The Start
# menu shortcut made by the installer carries the same ID.
APP_USER_MODEL_ID: Final = f"Indrajit147.{APP_NAME}"

# Named pipe used for IPC and as the single-instance lock (made per-user at runtime).
PIPE_NAME: Final = f"{APP_SLUG}-ipc"

# On-disk download format (decision D8): "name.ext" + suffix.
PARTIAL_SUFFIX: Final = ".odm-part"
STATE_SUFFIX: Final = ".odm-state"
LOCK_SUFFIX: Final = ".odm-lock"
