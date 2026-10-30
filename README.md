# OpenDM

A free, open-source, no-subscription download manager for Windows.

> **Status: early development (milestone M5, video and audio).** It works from source; there is
> no installer yet. See [PROGRESS.md](PROGRESS.md) and the
> [project specification](docs/PROJECT_SPEC.md).

## Features

Working now:

- Fast multi-connection downloads (up to 32 connections) with pause, resume and crash recovery
- Queues with schedules, categories with their own folders, speed limits, searchable history
- Desktop app with light/dark theme, tray icon, notifications, drag and drop of links
- Video and audio from many websites via [yt-dlp](https://github.com/yt-dlp/yt-dlp), with
  FFmpeg merging: quality picker, audio-only MP3/M4A, subtitles, playlists. The tools are
  downloaded only with your consent and verified against their published checksums.
  DRM-protected content is not supported.
- `opendm-cli` command line, talking to the running app or standalone
- No telemetry, no ads, no subscription

Planned:

- Chrome and Edge extension: download takeover, context menu, media detection
- Per-user installer (no admin rights) and a portable build

## Disclaimer

You are responsible for making sure you have the right to download any content you use
OpenDM for. OpenDM does not support DRM-protected or encrypted content and does not bypass
paywalls, logins or CAPTCHAs.

OpenDM is an independent project and is not affiliated with any commercial download manager.

## Development

See [CLAUDE.md](CLAUDE.md) for working rules and [docs/TESTING.md](docs/TESTING.md) for the
test setup. Quick start (CMD):

```
D:\Tools\Python312\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest -q
```

Run the app with `.venv\Scripts\opendm.exe` (or `.venv\Scripts\python.exe -m opendm`), and the
command line with `.venv\Scripts\opendm-cli.exe --help`.

## License

Copyright (C) 2026 Indrajit Gupta.
OpenDM is free software, licensed under the [GNU GPL v3.0 or later](LICENSE).
Third-party components are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
