# OpenDM

A free, open-source, no-subscription download manager for Windows.

> **Status: early development (milestone M0, foundations).** Nothing is usable yet.
> See [PROGRESS.md](PROGRESS.md) and the [project specification](docs/PROJECT_SPEC.md).

## Planned features

- Fast multi-connection downloads with pause, resume and crash recovery
- Video and audio from many websites via [yt-dlp](https://github.com/yt-dlp/yt-dlp), with FFmpeg merging
- Chrome and Edge extension: download takeover, context menu, media detection
- Queues, scheduling, categories, speed limits and history
- Per-user installer (no admin rights) and a portable build
- No telemetry, no ads, no subscription

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

## License

Copyright (C) 2026 Indrajit Gupta.
OpenDM is free software, licensed under the [GNU GPL v3.0 or later](LICENSE).
Third-party components are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
