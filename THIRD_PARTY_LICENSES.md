# Third-party licenses

OpenDM is licensed under GPL-3.0-or-later. This file lists third-party components and
their licenses. Every dependency's license is verified before it is added.

## Shipped with the app

Verified from installed package metadata (M1, 2026-10-30):

| Component | Version | License | Use |
|-----------|---------|---------|-----|
| httpx | 0.28.1 | BSD-3-Clause | HTTP client |
| httpcore | 1.0.9 | BSD-3-Clause | httpx dependency |
| h11 | 0.16.0 | MIT | httpcore dependency |
| anyio | 4.15.1 | MIT | httpx dependency |
| idna | 3.20 | BSD-3-Clause | httpx dependency |
| certifi | 2026.10.23 | MPL-2.0 | CA certificates for TLS |
| typing_extensions | 4.16.0 | PSF-2.0 | anyio dependency |
| PySide6-Essentials (Qt for Python) | 6.12.0 | LGPL-3.0-only (or GPL-2.0/3.0) | GUI (M4) |
| shiboken6 | 6.12.0 | LGPL-3.0-only (or GPL-2.0/3.0) | PySide6 runtime |

Qt is used under the LGPL-3.0 as dynamically linked libraries; the installer (M7) will ship
the Qt license texts and note where to get the Qt source code. Toolbar icons are Qt's built-in
standard icons (part of Qt, LGPL); the app icon is original artwork drawn in code
(`gui/icons.py`, GPL-3.0-or-later like the rest of OpenDM).

## Downloaded at runtime with user consent (not bundled)

| Component | Source | License | Use |
|-----------|--------|---------|-----|
| yt-dlp (`yt-dlp.exe`) | github.com/yt-dlp/yt-dlp releases | Unlicense (the Windows build bundles third-party components listed in its own release notes) | finds and downloads media |
| FFmpeg (`ffmpeg.exe`, `ffprobe.exe`) | gyan.dev "release essentials" | GPL-3.0 (this build includes GPL components such as x264); `LICENSE.txt` is kept next to the binaries | merging, remuxing, audio extraction |

OpenDM does not ship these tools; the user downloads them through the tool manager after
consenting, and they run as separate programs.

## Development only (not shipped)

| Component | License |
|-----------|---------|
| pytest | MIT |
| pytest-asyncio | Apache-2.0 |
| pytest-cov / coverage | MIT / Apache-2.0 |
| pytest-qt | MIT |
| ruff | MIT |
| setuptools (build backend) | MIT |
| Node.js 26 (runs the extension's tests; the extension itself has no dependencies) | MIT |
