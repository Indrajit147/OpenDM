Third-party software in this folder of OpenDM
=============================================

OpenDM itself is licensed under the GNU GPL v3.0 or later (see ..\LICENSE).
The full list of components is in ..\THIRD_PARTY_LICENSES.md.

Qt and Qt for Python (PySide6, shiboken6)
  The Qt libraries (Qt6*.dll, the PySide6 and shiboken6 folders under _internal) are used
  under the GNU LGPL v3.0 (LGPL-3.0.txt here). They are separate, dynamically loaded
  libraries: you may replace them with your own build of the same version.
  Source code: https://code.qt.io and https://download.qt.io/official_releases/QtForPython/
  Copyright (C) The Qt Company Ltd. and other contributors.

Python
  The Python runtime (python3*.dll and the standard library) is under the PSF License
  Agreement: https://docs.python.org/3/license.html

PyInstaller bootloader
  The small program that starts OpenDM.exe, opendm-cli.exe and opendm-host.exe comes from
  PyInstaller (GPL-2.0-or-later with the PyInstaller bootloader exception, which allows
  distributing programs built with it under any license).
  Source code: https://github.com/pyinstaller/pyinstaller

httpx, httpcore, h11, anyio, idna, certifi
  BSD-3-Clause / MIT / MPL-2.0 licenses; see ..\THIRD_PARTY_LICENSES.md.
