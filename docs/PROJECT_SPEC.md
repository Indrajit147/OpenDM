# OpenDM: Project Specification (master document for Claude Code)

> **App name:** "OpenDM" is a placeholder. Confirm the final name with the user in M0 and keep it in ONE constant (`src/opendm/core/branding.py`) so it can be renamed easily.
>
> **This file is the source of truth.** If anything here conflicts with a request or seems wrong, stop and ask the user. Do not silently deviate.

---

## 0. How Claude Code must use this document

1. Work **one milestone at a time** (Section 9). Never start the next milestone without the user's explicit approval.
2. For every milestone follow the **workflow in Section 10**: plan → wait for approval → tests first → implement → run tests → report → update docs.
3. In M0, create a short `CLAUDE.md` (≤ 80 lines) summarizing the rules in Sections 2, 3 and 10 and pointing to this file. Keep this spec in `docs/PROJECT_SPEC.md`.
4. Maintain `PROGRESS.md` (what is done, what is next, open questions) and `docs/DECISIONS.md` (one entry per architectural decision: context, options, pros/cons, choice). Update both at the end of every work session.
5. **Ask before downloading or installing anything** (Section 3).

---

## 1. Vision and goals

A **free, open-source, no-subscription download manager for Windows**, with a polished GUI, a CLI, and browser integration, that ordinary people can install from a normal installer and use without a terminal.

**It must be able to:**
- Download direct files fast with multiple connections, pause and resume them, and recover from crashes and network drops.
- Download video/audio from thousands of websites (via yt-dlp), including unencrypted HLS/DASH streams, playlists, quality selection and subtitles.
- Catch downloads and detect media in Chrome and Edge through a browser extension.
- Manage queues, schedules, categories, speed limits and history.
- Be installed, updated and uninstalled cleanly by non-technical users.

**Non-goals (never implement):**
- DRM circumvention, decrypting protected streams, paywall/login/auth bypass, CAPTCHA solving.
- Copying code, assets, icons, names or UI of any commercial download manager.
- macOS/Linux in v1 (but keep `core/` and `engine/` OS-agnostic so it is possible later).

**v1.0 success criteria:**
- A user downloads the installer from GitHub Releases, installs it without admin rights, installs the browser extension, and downloads a large file and a video with a few clicks.
- A 1 GB download survives killing the app mid-way and resumes to a correct SHA-256.
- The UI never freezes during downloads.

---

## 2. Legal and ethical ground rules

- **Clean-room implementation.** Build only from public specifications and documentation: RFC 9110 (HTTP semantics, Range requests), RFC 6266/RFC 5987 (Content-Disposition filenames), RFC 8216 (HLS), ISO/IEC 23009-1 (DASH, via public docs), MDN, Chrome Extensions docs, yt-dlp and FFmpeg docs.
- **Never** decompile, disassemble, debug, or inspect the binaries, extensions or network protocols of IDM or any other commercial download manager. Do not suggest doing so.
- Do not use "IDM" or "Internet Download Manager" in the app name, logo, icons, or UI. The UI layout may be familiar (a table of downloads with a sidebar of categories is a generic pattern) but must be an original design with original or openly licensed assets.
- **DRM-protected or encrypted streams are unsupported.** Detect them (yt-dlp reports DRM; encrypted HLS with `METHOD=SAMPLE-AES` or Widevine/PlayReady signaling in DASH) and show a clear "protected content is not supported" message.
- README includes a disclaimer: users are responsible for having the right to download the content.
- **License:** GPL-3.0-or-later for the project. Include `THIRD_PARTY_LICENSES.md` covering PySide6 (LGPL-3.0), httpx (BSD-3), yt-dlp (Unlicense), FFmpeg (LGPL/GPL depending on build), and any others. Verify every dependency's license before adding it.

---

## 3. Developer environment (the user's machine)

- **HP laptop, Windows 11.** The user prefers **CMD over PowerShell**. Give CMD commands. Use PowerShell only if CMD cannot do the job, and say so.
- **The C: drive is nearly full.** Keep everything on D: or E:.
  - Repo: `D:\Projects\opendm`
  - Virtual env: `D:\Projects\opendm\.venv`
  - pip cache: `PIP_CACHE_DIR=D:\pipcache`
  - PyInstaller build/work dirs: inside the repo (`build\`, `dist\`), never `%TEMP%` on C:.
  - Test downloads and fixtures: inside the repo or a D:/E: path the user chooses.
- **ASK BEFORE ANY DOWNLOAD OR INSTALL.** Before downloading or installing any tool, binary, SDK, or large dataset (e.g., FFmpeg, yt-dlp, Inno Setup, Node.js, test videos), stop and ask the user:
  1. what you want to install and why,
  2. its approximate size,
  3. **which folder to put it in** (suggest `D:\Tools\<name>`).
  Never install to C: unless the user explicitly approves. Also ask before adding any new Python/npm dependency.
- Python 3.12 (x64). Tooling: `ruff` (lint+format), `pytest`, `pytest-asyncio`, `pytest-qt`.

---

## 4. Key design decisions (pros and cons)

Record each in `docs/DECISIONS.md`. ✅ = chosen.

| # | Decision | Options considered | Choice and reason |
|---|----------|--------------------|-------------------|
| D1 | Language and GUI | ✅ Python 3.12 + PySide6 · C#/.NET WPF · Rust/Tauri · Electron | Python: fastest to a working product, the user knows Python, PySide6 gives a native-looking, high-DPI Qt UI. Cons: bigger installer (~80–120 MB), slower raw performance. Mitigation: downloading is network-bound, not CPU-bound. |
| D2 | Concurrency | ✅ Engine runs its own asyncio loop in a background thread; GUI talks to it via thread-safe commands and Qt signals · qasync (single loop) · thread per connection | Background loop keeps the GUI responsive, keeps the engine GUI-free and testable, and avoids qasync edge cases. Cons: need a clean command/event bridge (`core/bridge.py`). |
| D3 | HTTP client | ✅ httpx (async) · aiohttp · urllib | httpx: clean API, HTTP/1.1 + optional HTTP/2, good timeouts and proxy support. aiohttp is slightly faster but has rougher edges. Hide behind a `Transport` interface so it can be swapped. |
| D4 | Media sites and HLS/DASH | ✅ Delegate to yt-dlp · write own HLS/DASH parser and site extractors | yt-dlp supports thousands of sites, generic m3u8/mpd URLs, playlists, subtitles, and is actively maintained. Writing our own would be huge and always out of date. Our own engine handles direct files. Cons: external dependency that breaks when sites change. Mitigation: independent yt-dlp updater (D5). |
| D5 | yt-dlp integration | ✅ Official `yt-dlp.exe` run as a subprocess · import as a Python library | Subprocess can be updated independently of our app (critical, since sites change weekly) and isolates crashes. Cons: progress must be parsed from output. Use `--newline` and `--progress-template` with a machine-readable (JSON) template. |
| D6 | FFmpeg | ✅ Downloaded on first use by the Tool Manager into a user-chosen folder · bundled in the installer | Keeps the installer small and avoids GPL redistribution complexity. Cons: first media download needs a one-time tool download (with consent dialog). |
| D7 | Persistence | ✅ SQLite (stdlib `sqlite3`, WAL mode) · JSON files | Atomic, queryable history, safe concurrent access. Use a small migration system. |
| D8 | On-disk download format | ✅ One preallocated target file (`name.ext.odm-part`) with positioned writes plus a small state sidecar · one temp file per segment then merge | Single file needs no merge step, so no doubled disk usage, which matters on a full disk. Rename to the final name on completion. |
| D9 | Browser ↔ app | ✅ MV3 extension + Native Messaging host · localhost HTTP server | Native Messaging is the officially supported channel, and only our extension can reach it. A localhost server risks port conflicts and lets any website try to call it. |
| D10 | Host ↔ running app IPC | ✅ Qt `QLocalServer`/`QLocalSocket` (Windows named pipe) · TCP localhost | Named pipe is user-scoped, needs no port, and doubles as the single-instance lock. |
| D11 | Packaging | ✅ PyInstaller **onedir** · PyInstaller onefile · Nuitka | Onedir: fast startup and fewer antivirus false positives than onefile. Nuitka is faster but builds are slower and more complex. Revisit Nuitka after v1 if needed. |
| D12 | Installer | ✅ Inno Setup, per-user install (no admin) · WiX/MSI · MSIX | Inno Setup is free, scriptable, supports a directory-choice page, and can write HKCU registry keys for Native Messaging. MSIX requires signing and has restrictions. |
| D13 | Updates and telemetry | ✅ Opt-in update check against GitHub Releases; **no telemetry** | Simple, transparent and privacy-respecting. |
| D14 | Research approach | ✅ Clean-room from public specs + local test server · reverse engineering commercial binaries | Reverse engineering is a legal risk for a public repo, slow, and unnecessary because the techniques are public standards. |
| D15 | Browsers | ✅ Chrome + Edge first (same MV3 code) · Firefox | Chrome and Edge cover most Windows users with one codebase. Firefox is a post-1.0 milestone. |

---

## 5. Architecture

```
 Browser (Chrome/Edge)
   └─ MV3 extension: download takeover, context menu, media detection, video button
        │  Native Messaging (JSON over stdio)
        ▼
 opendm-host.exe  (validates messages, launches the app if needed)
        │  Named pipe (QLocalSocket), current user only
        ▼
 OpenDM.exe  (GUI process, single instance)
   ├─ GUI (PySide6)  ◄── Qt signals ──┐
   ├─ CLI bridge (opendm-cli.exe talks over the same pipe)
   └─ Engine thread (asyncio)
        ├─ Discovery: classify URL → direct file | media page | manifest
        ├─ HTTP engine: probe, segment planner, workers, writer, resume, rate limit
        ├─ Media engine: yt-dlp runner, FFmpeg runner
        ├─ Queue/scheduler
        ├─ Tool manager (yt-dlp, FFmpeg: download, verify, update)
        └─ Storage (SQLite)
```

**Package layout**
```
src/opendm/
  core/        models (Job, Segment, Settings), events, bridge, paths, branding, logging, errors
  engine/http/ probe.py, planner.py, worker.py, writer.py, resume.py, ratelimit.py, transport.py
  engine/media/ ytdlp.py, ffmpeg.py, formats.py, drm.py
  discovery/   classify.py, content_types.py
  queue/       scheduler.py, queues.py, host_limits.py
  storage/     db.py, migrations/, repositories.py
  tools/       manager.py, sources.py (official URLs + checksum verification)
  ipc/         server.py, client.py, single_instance.py
  host/        __main__.py (Native Messaging host)
  cli/         __main__.py
  gui/         app.py, main_window.py, dialogs/, models/, widgets/ (segment map), tray.py, theme.py, resources/
  updater/     github_releases.py
extension/     manifest.json, background.js, content.js, popup/, options/, icons/
installer/     opendm.iss
tests/         unit/, integration/, gui/, server/ (local test server), fixtures/ (generated, git-ignored)
docs/          PROJECT_SPEC.md, DECISIONS.md, PRIVACY.md, TESTING.md, USER_GUIDE.md
```

**Rules:** `core/` and `engine/` must not import Qt. The GUI never calls network or disk-heavy code directly. All engine ↔ GUI traffic goes through `core/bridge.py`.

---

## 6. Feature specification (v1.0)

### 6.1 HTTP/HTTPS download engine
- **Probe:** `HEAD`, falling back to `GET` with `Range: bytes=0-0` if HEAD fails or lies. Determine size, `Accept-Ranges`, `ETag`/`Last-Modified`, content type, final URL after redirects, and filename (Content-Disposition per RFC 6266/5987, then URL path, then content type).
- **Segmentation:** default 8 connections, user range 1–32, minimum segment 1 MiB, per-host connection limit (default 8).
- **Dynamic splitting:** when a worker finishes, split the largest remaining segment and start a new worker on its second half.
- **Writing:** preallocate the file, use positioned writes, buffer ≤ 4 MiB per connection, flush state every 2 s and on pause or exit.
- **Resume:** use `If-Range` with ETag/Last-Modified. If the validator changed, warn the user and offer a restart. Must survive app kill and reboot.
- **Fallbacks:** no Range support, or a `200` returned instead of `206`, → single-stream mode with clear UI status. Unknown Content-Length → single-stream, size shown as "unknown".
- **Retries:** exponential backoff with jitter, configurable max. Distinguish retryable errors (timeouts, 5xx, connection reset) from fatal ones (404, 410, disk full).
- **Expired links (403/410 mid-download):** "Refresh link" flow. The user re-captures the link from the browser, and progress is kept if size and validator still match.
- **Speed limit:** global and per-download token bucket.
- **Other:** disk-space check before start, optional checksum verification (user-supplied SHA-256/SHA-1/MD5), custom headers, referrer, user agent, cookies, system proxy plus manual HTTP/SOCKS proxy, TLS verification on by default.

### 6.2 Media downloads (yt-dlp + FFmpeg)
- **Analyze URL:** run yt-dlp `-J` to get title, thumbnail, formats, playlist entries and subtitles.
- **Quality picker dialog:** Best, specific resolutions, audio-only (mp3/m4a), container choice, subtitles, thumbnail embed, and playlist item selection.
- **Progress:** parse the JSON progress template into the same job/progress model as HTTP downloads so the GUI treats both alike. Pause = terminate the process; resume = rerun with `--continue`.
- **Cookies:** when the browser extension passes cookies, write a temporary Netscape-format cookies file in the app data dir, readable only by the current user, pass it with `--cookies`, and delete it when the job ends. Never log cookie values.
- **DRM:** detect and show "protected content is not supported". No workarounds.
- **Merging and remuxing:** handled by FFmpeg via `--ffmpeg-location`.

### 6.3 Queue, scheduler, categories
- Multiple named queues, each with a max-concurrent setting, start and stop times, and days of week.
- After-queue actions: none, sleep, shutdown (with a 60 s cancelable countdown dialog).
- Categories by file extension (Video, Audio, Documents, Compressed, Programs, Other), each with its own default folder. User-editable.
- History with search, filters, "open file", "open folder", "redownload", "delete file and entry" (with confirmation).

### 6.4 GUI (PySide6)
- **Main window:** toolbar (Add URL, Resume, Pause, Stop all, Delete, Queues, Settings), left sidebar (categories, unfinished, finished, queues), and a download table (name, size, progress bar, speed, ETA, status, date added). Sortable, multi-select, right-click menu.
- **Add URL dialog:** auto-fills from the clipboard if it holds a URL. Batch mode accepts many URLs and patterns like `file[01-20].zip`.
- **Download-start dialog:** filename, folder, category, size, "start now" / "add to queue", checksum field.
- **Download details window:** live speed graph, connection count, and a **segment map** bar showing each connection's progress (an original visual design).
- **Settings:** general, connections, speed limits, folders/categories, browser integration status, tools (paths and versions, update button), proxy, appearance (system/light/dark), notifications, updates, language (English first; strings ready for translation, e.g., Bangla later).
- **System tray:** minimize to tray, quick actions, completion notifications (Windows toasts).
- **Clipboard monitor** (opt-in) and drag-and-drop of URLs and `.txt` link lists.
- **First-run wizard:** choose the default download folder (default = Windows Downloads folder; the user may pick D:/E:), choose the tools folder, and a step-by-step browser extension setup.
- High-DPI aware, keyboard accessible, no frozen UI ever. Throttle progress updates to ~4 Hz.
- **Icons/assets:** original or openly licensed (verify the license, record it in THIRD_PARTY_LICENSES.md).

### 6.5 Browser extension (Manifest V3, Chrome and Edge)
- **Download takeover:** listen to `chrome.downloads.onCreated`, cancel the browser download, and send it to the app. Configurable: on/off, file-type list, minimum size, and holding a modifier key to skip takeover. If the app is unreachable, let the browser download normally and show a notice.
- **Context menu:** "Download with OpenDM" on links, media, and "download all links on page" (with a selection dialog in the app).
- **Media detection:** observe response headers with `chrome.webRequest.onHeadersReceived` (non-blocking) for `video/*`, `audio/*`, `application/vnd.apple.mpegurl`, `application/x-mpegURL`, `application/dash+xml`, and `.m3u8`/`.mpd` URL patterns. Keep a per-tab list, show a toolbar badge count, and a popup listing detected media with a "Download" button.
- **Video button:** a content script adds a small, unobtrusive "Download" button over `<video>` elements (toggleable). `blob:` URLs are not files. Use the detected manifest/segment requests or send the page URL to yt-dlp.
- **Data sent to the app, only on user action or takeover:** URL, page URL, page title, referrer, user agent, and cookies for that URL via `chrome.cookies`.
- **Limits:** MV3 cannot read response bodies. Use only supported APIs. Request minimal permissions and document each one in `docs/PRIVACY.md`. Never collect browsing history.
- **Stable extension ID:** use the `key` field in `manifest.json` during development so the Native Messaging `allowed_origins` stays valid. Add store IDs at release.

### 6.6 Native Messaging host
- `opendm-host.exe`: reads length-prefixed JSON from stdin, validates it against a schema, allows only the schemes `http`, `https` (and `ftp` later), and forwards to the app over the named pipe. Launches the app if it is not running.
- Respect message size limits (host → browser ≤ 1 MB).
- Register under `HKCU\Software\Google\Chrome\NativeMessagingHosts\<host-name>` and `HKCU\Software\Microsoft\Edge\NativeMessagingHosts\<host-name>` (installer does this; a dev script `scripts\register_host_dev.cmd` does it for development).

### 6.7 CLI (`opendm-cli.exe`)
- `opendm-cli get <url> [-o DIR] [-c N] [--media] [--quality 1080p]`, `list`, `pause <id>`, `resume <id>`, `remove <id>`.
- Talks to the running app over IPC. With `--standalone`, it runs the engine directly without the GUI.

### 6.8 Tool manager
- Downloads `yt-dlp.exe` from the official yt-dlp GitHub releases and verifies it against the release's published SHA-256 sums.
- Downloads an FFmpeg Windows build from a reputable source (e.g., BtbN or gyan.dev builds) and verifies its checksum.
- Always asks the user's consent and shows the destination folder, which the user can change.
- Checks for yt-dlp updates weekly (opt-in), with an "Update now" button. Shows tool versions in Settings and About.

### 6.9 App updater
- Opt-in check of GitHub Releases at startup. Show release notes, download the installer, verify its SHA-256, then run it. Never update silently.

### 6.10 Paths and data
- App data: `%LOCALAPPDATA%\OpenDM` by default (database, logs, settings).
- **Portable mode:** if `portable.flag` exists next to the exe, store all data next to the exe. Useful for D:/E: installs.
- Partial files and state sidecars live **next to the target file**, never in `%TEMP%`, so C: is not filled.
- The installer offers a directory-choice page. Per-user default is `%LOCALAPPDATA%\Programs\OpenDM`, and the user may choose D:/E:.

### 6.11 Logging and diagnostics
- Rotating log files. Redact cookies, auth headers and URL query strings by default.
- "Export diagnostics" button that zips logs and settings, with secrets removed.

---

## 7. Non-functional requirements

- **Responsiveness:** the GUI thread never does network or disk-heavy work.
- **Memory:** bounded buffers. Total app memory under ~250 MB with 10 active downloads.
- **Crash safety:** killing the process at any point must never corrupt completed files and must allow resume.
- **Security:**
  - Never use `shell=True`. Pass subprocess arguments as lists.
  - Sanitize filenames: Windows reserved names (CON, NUL, COM1…), illegal characters, trailing dots/spaces, path traversal, long paths.
  - Never auto-run downloaded files.
  - The named pipe is restricted to the current user.
  - Validate every IPC and Native Messaging message.
  - TLS verification is on by default. Disabling it requires an explicit per-download override with a warning.
- **Privacy:** no telemetry. Network calls happen only for user downloads and opt-in update checks.
- **Platform:** Windows 10 (1809+) and Windows 11, x64.

---

## 8. Testing strategy

- **Local test server** (`tests/server/`, dev-only dependency) with fault injection:
  - Range supported; Range unsupported; `200` instead of `206`
  - No Content-Length; Content-Disposition with UTF-8 filenames
  - Redirects; throttling; connection drop at byte N
  - ETag change mid-download; 403 after N seconds (expired link)
  - Slow start; gzip encoding; cookie-protected route; 404/500
- **Media fixtures:** generate a short MP4, an unencrypted HLS stream, and an unencrypted DASH stream with FFmpeg (ask the user for the FFmpeg path first). Fixtures are generated by a script and git-ignored.
- **Unit tests:** planner, splitter, resume logic, filename sanitizer, rate limiter, yt-dlp output parser, DB migrations.
- **Integration tests:** full downloads against the test server, including kill-and-resume and SHA-256 checks.
- **GUI smoke tests:** pytest-qt (window opens, add a download, progress updates, pause/resume).
- **Extension:** unit-test pure JS logic where practical, plus a manual checklist in `docs/TESTING.md` run against local test pages served by the test server.
- **No internet in default tests.** Tests that hit real sites carry `@pytest.mark.live` and are skipped by default.
- **Coverage target:** ≥ 85% for `engine/` and `core/`.
- **CI:** GitHub Actions on `windows-latest` runs ruff and pytest on every push and PR.

---

## 9. Milestones

Each milestone ends with: all tests green, `ruff check .` clean, docs updated, `PROGRESS.md` updated, a summary for the user, and a **manual test checklist the user can follow in CMD/GUI**.

### M0 Foundations
- Confirm the final app name. Ask which tools/paths are needed (Section 3).
- Repo skeleton (Section 5 layout), `pyproject.toml`, ruff, pytest config, `.gitignore`, LICENSE (GPL-3.0-or-later), README stub, `CLAUDE.md`, `PROGRESS.md`, `docs/DECISIONS.md` (prefilled from Section 4), GitHub Actions CI.
- Local test server with fault injection.
- **Accept:** `pytest -q` green; the test server serves every fault case; CI config valid.

### M1 Single-stream engine + CLI
- Probe, filename detection, single-stream download, progress events, pause/cancel, error model, filename sanitizer, `opendm-cli get --standalone`.
- **Accept:** downloads from the test server with correct SHA-256 and correct filenames from Content-Disposition, including UTF-8 names.

### M2 Multi-connection engine
- Segment planner, dynamic splitting, preallocated positioned writes, state sidecar, resume with If-Range, retries/backoff, Range fallbacks, speed limiter, checksum verification, expired-link refresh API.
- **Accept:** a 100 MB file over 8 connections; killing the process mid-way and resuming gives a correct SHA-256; no-Range and 200-instead-of-206 fall back correctly; an ETag change is detected; the speed limit holds within ±10%.

### M3 Storage, queue, scheduler
- SQLite schema and migrations, job repository, queues, per-host limits, scheduling, categories, history.
- **Accept:** jobs persist across restarts, queue concurrency is respected, and schedule start/stop works (with an injectable test clock).

### M4 GUI v1
- Engine thread + bridge, main window, Add URL (with batch), download-start dialog, details window with segment map, settings, tray, notifications, first-run wizard, single instance, clipboard monitor, drag-and-drop, light/dark theme.
- **Accept:** pytest-qt smoke tests pass, the user's manual checklist passes, and the UI stays smooth during 10 parallel downloads.

### M5 Tool manager + media engine
- Tool manager (consent, path choice, checksum verification, updates), yt-dlp analysis, quality picker, playlists, subtitles, FFmpeg merge, DRM detection message, unified progress.
- **Accept:** local HLS/DASH/MP4 fixtures download and merge correctly; encrypted test fixtures produce the "not supported" message; yt-dlp updates from the Settings button.

### M6 Browser extension + Native Messaging host
- MV3 extension (takeover, context menu, media detection, video button, popup, options), host exe, dev registration script, IPC.
- **Accept:** loaded unpacked in Chrome and Edge, all checklist items in `docs/TESTING.md` pass against local test pages, including the cookie-protected route and app-not-running behavior.

### M7 Packaging
- PyInstaller onedir builds for `OpenDM.exe`, `opendm-cli.exe`, `opendm-host.exe`. Inno Setup per-user installer with directory choice, Start menu entry, Native Messaging registration (Chrome + Edge), optional desktop icon, and a clean uninstaller (removes registry keys; asks before deleting user data). Portable ZIP build.
- **Accept:** install, use, and uninstall on a clean Windows user account (or Windows Sandbox if available) without admin rights; no leftovers except user-chosen data.

### M8 Release pipeline + updater
- GitHub Actions release workflow on version tags: build, run tests, produce the installer + portable ZIP + SHA-256 sums, and draft release notes from `CHANGELOG.md`. In-app update check (opt-in) and yt-dlp auto-update check.
- **Accept:** pushing a test tag produces a complete draft release; the app detects a newer test release.

### M9 Hardening and public launch (v1.0.0)
- Security review against Section 7, performance pass, and docs: README with screenshots, install guide, user guide, FAQ, PRIVACY.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates.
- Prepare Chrome Web Store (one-time developer registration fee) and Edge Add-ons listings.
- Document code signing options: unsigned builds trigger Windows SmartScreen warnings, so apply to a free open-source code-signing program such as SignPath Foundation (check current eligibility).
- **Accept:** the user approves the release checklist; tag v1.0.0.

### M10 Post-1.0 (optional, separate approval each)
BitTorrent/magnet (libtorrent), FTP/SFTP, Firefox extension, Bangla localization, winget package, Nuitka build experiment.

---

## 10. Working agreement for Claude Code

For **every** milestone:
1. **Plan first:** goals, files to create/change, interfaces and data models, edge cases, acceptance tests, any new dependency (name, license, size, why), and anything that must be downloaded (ask for the path).
2. **Wait for the user's approval.**
3. Write tests first for engine logic, then implement in small steps with **Conventional Commits** (`feat:`, `fix:`, `test:`, `docs:`…), one logical change per commit.
4. Run `pytest -q` and `ruff check .` and actually read the results. **Never claim something works without running it.** If something can't be tested automatically, say so and add it to the manual checklist.
5. Report: what was built, test results, failures, design decisions, and known limitations.
6. Update `PROGRESS.md`, `docs/DECISIONS.md`, and user docs.
7. Stop and wait. Do not start the next milestone on your own.

**Always:**
- Give the user **CMD** commands. Keep everything off C:.
- Ask before downloads, installs, or new dependencies.
- Never commit secrets, cookies, large binaries, or generated fixtures.
- Prefer simple, readable code with docstrings and type hints (mypy-friendly).
- If a requirement is unclear or seems wrong, ask instead of guessing.
- If context is getting long, update `PROGRESS.md` so a new session can continue cleanly.

---

## Appendix A. Kickoff prompt (first Claude Code session)

> Read `PROJECT_SPEC.md` completely. It is the source of truth for this project. We are starting **Milestone M0 only**.
>
> Before writing anything:
> 1. Summarize your understanding of the project in about 10 bullets.
> 2. List every question you need answered, including the final app name and the install folder for anything you need to download (never C:).
> 3. Give the M0 plan: files to create, commands to run (CMD), dependencies (with licenses), and acceptance tests.
>
> Then wait for my answers and approval. Follow Section 10 for every milestone.

## Appendix B. Resume prompt (any later session)

> Read `CLAUDE.md`, `PROGRESS.md`, and the current milestone in `docs/PROJECT_SPEC.md`. Tell me where we are, what's left in this milestone, and the next step. Wait for my approval before changing anything.
