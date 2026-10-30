# Progress

## Current milestone: M4 GUI v1 (complete, awaiting user review)

### M4 done (2026-10-30)
- Dependencies: PySide6-Essentials 6.12.0 + shiboken6 (LGPL-3.0), pytest-qt 4.5.0 (dev, MIT).
- `core/bridge.py`: engine thread (loop + DB + manager), futures for commands, job snapshots
  and coalesced progress for the GUI. `core/batch.py` (`[01-20]` patterns, URL lists),
  `core/app_settings.py` (user settings, proxy modes).
- `ipc/`: validated JSON-lines protocol, user-only named-pipe server, Qt-free client, per-user
  named-mutex single-instance lock (the pipe alone is not exclusive on Windows: D44).
- CLI: `get` (without `--standalone`), `list`, `pause`, `resume`, `remove [--delete-file]` go
  through the running app.
- `gui/`: main window (toolbar, sidebar views, sortable table with progress bars, context menu,
  search, drag and drop, status bar), Add URL (batch), start dialog (probe, category/folder,
  queue, checksum), details (speed graph, segment map, connections), settings, queues, first-run
  wizard, tray + notifications, opt-in clipboard monitor, light/dark/system theme, 60 s
  countdown for sleep/shutdown, app icon drawn in code, `opendm.exe` / `python -m opendm`.
- Engine: manual HTTP proxy / no proxy; manager `probe`, `apply_settings`, `move_to_queue`.
- Fixed: a job's name could include the URL query string before the first probe.
- Decisions D42–D48.

### Results
- `pytest -q`: 493 passed. `ruff check .` / `ruff format --check .`: clean.
- Smoothness (acceptance): 10 parallel downloads, longest UI stall < 100 ms measured with a 10 ms
  heartbeat; table updates 2-5 per row per second.
- Visual check with `scripts/screenshots.py` (real Windows rendering, nothing shown on screen):
  main window, details (8-connection segment map), start dialog. Fixed from it: busy bar on
  failed rows, wrapped status text, cut-off dates.

### Manual checklist run (in progress, 2026-10-30)
- Steps 1-2 passed on the user's PC (app starts, download completes, notification shown).
- Fixed from it: Name column squeezed to "t...p" with a horizontal scrollbar at the default
  window size (columns now fit the table on every resize; regression test); the wizard now
  warns in orange when the chosen drive has < 30 GiB free; checklist explains copying links
  (not opening them in a browser) and that test files are random bytes.
- Open: Windows notifications say "Python" because the app runs as python.exe; the M7
  installer gives OpenDM its own identity (Start-menu shortcut with an AppUserModelID).

### Known limitations
- Tray, notifications and the clipboard monitor are only partly covered by automated tests
  (no tray in the offscreen platform).
- No logging/diagnostics export yet (spec 6.11), no translations yet (strings use `tr()`).
- SOCKS proxy deferred (needs `socksio`). A running download does not pick up settings changes.
- Toolbar icons are Qt's standard icons; a nicer original icon set can come later.

### Earlier milestones
- **M3 (2026-10-30):** SQLite storage, encrypted secrets, DownloadManager (queues, host limits,
  schedules), categories, history. D35–D41.
- **M2 (2026-10-30):** multi-connection engine, crash-safe resume, retries, fallbacks, speed
  limits, checksums. D27–D34.
- **M1 (2026-10-30):** errors, events, filename handling, probe, CLI. D20–D26.
- **M0 (2026-10-30):** Python 3.12.10 at `D:\Tools\Python312`, skeleton, tooling, GPL-3.0, test
  server, CI. D1–D19.

### Next
- User runs the M4 manual checklist and reviews.
- On approval: plan **M5 Tool manager + media engine** (yt-dlp/FFmpeg downloads need consent and
  a folder).

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager from the Terminal panel tab.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- A refused TCP connection takes ~2 s on Windows; avoid repeating them in tests.
- PowerShell 5.1 `Set-Content -Encoding utf8` adds a BOM; prefer the Write/Edit tools.
- The user's Downloads folder is `C:\Users\Hp\Downloads`; tests never write there.
- Offscreen Qt has no usable fonts on Windows; use `scripts/screenshots.py` for visual checks.
