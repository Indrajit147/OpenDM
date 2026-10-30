"""Small Windows shell calls (no-ops elsewhere)."""

import sys


def set_app_user_model_id(app_id: str) -> bool:
    """Give this process its own taskbar and notification identity (not "Python")."""
    if sys.platform != "win32":
        return False
    import ctypes

    shell32 = ctypes.WinDLL("shell32")
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    return shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
