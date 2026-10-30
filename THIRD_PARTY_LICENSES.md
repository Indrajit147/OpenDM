# Third-party licenses

OpenDM is licensed under GPL-3.0-or-later. This file lists third-party components and
their licenses. Every dependency's license is verified before it is added.

## Shipped with the app

None yet. Planned (to be verified and recorded when added):

| Component | License | Use |
|-----------|---------|-----|
| PySide6 (Qt for Python) | LGPL-3.0 | GUI (M4) |
| httpx | BSD-3-Clause | HTTP client (M1) |

## Downloaded at runtime with user consent (not bundled)

| Component | License | Use |
|-----------|---------|-----|
| yt-dlp | Unlicense | media extraction (M5) |
| FFmpeg | LGPL-2.1+ or GPL-2.0+/3.0+, depending on build | merging/remuxing (M5) |

## Development only (not shipped)

| Component | License |
|-----------|---------|
| pytest | MIT |
| pytest-asyncio | Apache-2.0 |
| pytest-cov / coverage | MIT / Apache-2.0 |
| ruff | MIT |
| setuptools (build backend) | MIT |
