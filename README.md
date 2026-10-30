# OpenDM

A free, open-source, no-subscription download manager for Windows.

> **Status: early development (milestone M7, installer).** Builds are not published yet
> (release downloads come with M8). See [PROGRESS.md](PROGRESS.md) and the
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
- Chrome and Edge extension (load unpacked for now): download takeover with cookies, context
  menu, "download all links", video button and media detection. See
  [docs/PRIVACY.md](docs/PRIVACY.md) for what it sends and why each permission is needed.
- `opendm-cli` command line, talking to the running app or standalone
- Per-user installer (no admin rights) and a portable build
- No telemetry, no ads, no subscription

Planned:

- Published releases on GitHub with an opt-in update check

## Install

- **Installer** (`OpenDM-<version>-setup.exe`): installs for your Windows account only, no
  admin rights. Default folder `%LOCALAPPDATA%\Programs\OpenDM`; you can choose another drive.
  The builds are not code-signed yet, so Windows SmartScreen may warn: choose "More info" ->
  "Run anyway" only if you got the file from this repository's releases.
- **Portable** (`OpenDM-<version>-portable.zip`): unzip anywhere (for example a USB drive) and
  run `OpenDM.exe`. Settings and history stay in the `data` folder next to it.
- **Browser:** in OpenDM open Settings -> Browser, click "Set up for Chrome and Edge", then load
  the `extension` folder shown there as an unpacked extension.
- **Uninstall:** Windows Settings -> Apps -> OpenDM. It asks whether to delete your settings and
  history; downloaded files are never deleted.

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

Build the programs, portable ZIP and installer with `scripts\build.cmd` (needs PyInstaller from
`.[dev]` and Inno Setup 6). Run the app from source with `.venv\Scripts\opendm.exe` (or
`.venv\Scripts\python.exe -m opendm`), and the command line with `.venv\Scripts\opendm-cli.exe --help`. For the browser extension, run
`scripts\register_host_dev.cmd` once and load `extension\` unpacked (steps in
[docs/TESTING.md](docs/TESTING.md), M6).

## License

Copyright (C) 2026 Indrajit Gupta.
OpenDM is free software, licensed under the [GNU GPL v3.0 or later](LICENSE).
Third-party components are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
