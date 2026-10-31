# Changelog

All notable changes to OpenDM. The release workflow copies a version's section into the
GitHub release notes. Versions follow `X.Y.Z`, with `-rc.N` for test releases.

## [1.0.1] - 2026-10-31

### Added
- The OpenDM extension from Microsoft Edge Add-ons can talk to the app. Installing or
  updating OpenDM sets this up; with the portable ZIP, click *Repair* in Settings -> Browser.
- The extension tells apart "OpenDM is not installed" (with a link to get it), "OpenDM needs
  an update" and "OpenDM is not running".
- Code signing policy in the README; the release workflow is ready to sign builds through
  SignPath once the project is accepted (until then builds stay unsigned).

## [1.0.0] - 2026-10-31

First public release.

### Added
- Log files (5 x 1 MB, link tokens, cookies and passwords removed) and Settings -> General ->
  Export diagnostics: a ZIP of logs, settings and versions to attach to a bug report.
- When a website's certificate cannot be verified, the download dialog offers to skip the
  check for that one download, with a warning. Checks stay on otherwise.
- The installer shows what OpenDM sends where before you choose a folder.
- Install guide, user guide, FAQ, security policy, contributing guide and code of conduct;
  README with screenshots; issue and pull request templates.

### Fixed
- Moving yt-dlp and FFmpeg to their new folder no longer freezes the window at the first
  start after updating from 0.7.

## [0.8.0] - 2026-10-31

### Added
- Releases are built on GitHub from version tags: installer, portable ZIP and `SHA256SUMS.txt`.
- Optional update check (off until you turn it on): shows the release notes, downloads the
  installer, checks its SHA-256 and runs it only when you click Install. Pre-releases only if
  you ask for them. The portable version opens the release page instead. When GitHub's
  hourly limit for anonymous requests is reached, the check reads the public releases feed.
- yt-dlp and FFmpeg now live in their own `tools` folder next to OpenDM (portable:
  `data\tools`), never in Downloads. Tools found inside the download folder are moved there.
- If yt-dlp or FFmpeg goes missing, video and audio downloads wait and OpenDM offers once to
  download the tools again.
- A link to a video inside a playlist or YouTube Mix downloads just that video; the whole
  playlist is one click away.

### Fixed
- YouTube analysis failed with "Separator is not found, and chunk exceed the limit"
  (yt-dlp's answer is one line of several MB).
- Video and audio from YouTube failed with "Requested format is not available" when the
  browser sent its login cookies; OpenDM now retries once without them.
- A missing `yt-dlp.exe` showed "file not found" instead of "yt-dlp is not installed".
- The status bar counted downloads that the list did not show.
- The first-run wizard still said the browser extension was "coming later".

## [0.7.0] - 2026-10-30

### Added
- Per-user installer (no admin rights) with Start menu entry, optional desktop icon, Chrome
  and Edge setup, and a clean uninstaller; portable ZIP.
- Settings -> Browser to set up or remove the browser connection.

## [0.6.0] - 2026-10-30

### Added
- Chrome and Edge extension: download takeover with cookies, context menus, "download all
  links", video button and media detection; Native Messaging host.

## [0.5.0] - 2026-10-30

### Added
- Video and audio from many sites through yt-dlp and FFmpeg (downloaded only with consent and
  checked against their published checksums): quality picker, MP3/M4A, subtitles, playlists.
  DRM-protected content is refused.

## [0.4.0] - 2026-10-30

### Added
- Desktop app: downloads table, categories, queues, settings, tray icon, notifications,
  clipboard monitor, light/dark theme. `opendm-cli` talks to the running app.

## [0.3.0] - 2026-10-30

### Added
- Saved downloads, history, queues with schedules, per-host limits and categories.

## [0.2.0] - 2026-10-30

### Added
- Multi-connection downloads with crash-safe resume, retries, speed limits and checksums.

## [0.1.0] - 2026-10-30

### Added
- Single-connection downloads and `opendm-cli get`.
