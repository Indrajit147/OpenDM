"""Encrypt cookies and auth headers at rest with Windows DPAPI (current user).

Only the same Windows user on the same machine can decrypt. Off Windows nothing is
available, and callers must not store secrets at all.
"""

import ctypes
import sys

_ENTROPY = b"OpenDM secrets v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretsError(Exception):
    """Secrets cannot be protected or recovered here."""


def available() -> bool:
    return sys.platform == "win32"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _call(protect: bool, data: bytes) -> bytes:
    if not available():
        raise SecretsError("secret storage needs Windows DPAPI")
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    source, _keep1 = _blob(data)
    entropy, _keep2 = _blob(_ENTROPY)
    out = _Blob()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), None, ctypes.byref(entropy), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
        )  # fmt: skip
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, ctypes.byref(entropy), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
        )  # fmt: skip
    if not ok:
        raise SecretsError(f"DPAPI {'protect' if protect else 'unprotect'} failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    return _call(True, data)


def unprotect(blob: bytes) -> bytes:
    return _call(False, blob)
