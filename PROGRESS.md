# Progress

## Current milestone: M8 Release pipeline + updater (complete, awaiting user review)

### M8 done (2026-10-31)
- Version `0.8.0-rc.1` (pre-release versions: `opendm.core.version`), `CHANGELOG.md`,
  `scripts/release_notes.py`. Windows file version `0.8.0.0` passed to PyInstaller and Inno.
- `.github/workflows/release.yml`: on `v*` tags builds, tests (pytest, smoke, install test),
  writes `SHA256SUMS.txt` and notes, and creates a **draft** release (pre-release for `-rc`).
- Updater (`opendm.updater.github_releases`): opt-in startup check and "Check now", release
  notes, Install (download to `<install>\updates`, SHA-256 check, runs after OpenDM exits),
  Skip this version, Later; portable opens the release page. Settings -> Updates, wizard page.
- Tools folder (user request): `<install>\tools` / portable `data\tools`; never the download
  folder (refused in Settings and the tools prompt); tools in Downloads or in 0.7's
  `%LOCALAPPDATA%\OpenDM\tools` are moved on start; uninstall removes `tools` and `updates`.
- Missing tools: media jobs wait and the GUI asks once; they continue when the tools are back.
- Fixes: YouTube analysis with multi-MB output (64 KiB line limit), logged-in YouTube
  cookies hiding the streams (retry without cookies), "file not found" -> "yt-dlp is not
  installed", the status bar total after a removal, the wizard's outdated browser text; a
  video inside a playlist/Mix is analyzed alone with "Show the whole playlist...".
- Decisions D64-D66.

### Results
- `pytest` with real tools: 745 passed, 2 failed. The 2 are HTTP timing tests
  (`test_speed_limit_within_10_percent`, `test_external_cancellation_checkpoints`) that fail the
  same way on the pre-M8 commit on this PC tonight (slow local connection start under load);
  GitHub CI passed them (run 41097571459). 747 tests (671 before M8). Node: 13 passed.
  `ruff check`/`format`: clean.
- `scripts/smoke_dist.py` (0.8.0-rc.1 portable ZIP): 14/14. Version info shows 0.8.0-rc.1.
- `scripts/installer_test.py` was not run locally (OpenDM is installed on this PC; the test needs
  a machine without it). It passed in the release workflow, now also checking that upgrades
  keep `tools` and the uninstaller removes `tools` and `updates`.
- Release workflow for tag `v0.8.0-rc.1` (run 41098105660, 5 min): every step green, draft
  release created. Sizes: setup 26 MB, portable ZIP 45 MB.

### Known limitations
- The draft release must be published by the user (drafts are private).
- Unsigned builds: SmartScreen warns (signing options are M9).
- The updater was tested against a fake GitHub on the test server; the real path (rc.1 ->
  rc.2) is manual checklist step 7.
- YouTube videos that need a login still fail without a JavaScript runtime for yt-dlp
  (cookies are dropped on retry); planned for later.
- The user's manual checklists for M4 steps 9-14, M5, M6, M7 and M8 have not been reported.

### Earlier milestones
- **M7 (2026-10-30):** PyInstaller build, per-user Inno Setup installer, portable ZIP,
  Settings -> Browser, packaging tests. D60-D63. Fixes after review: long yt-dlp lines,
  cookie retry.
- **M6 (2026-10-30):** Native Messaging host, MV3 extension for Chrome/Edge (takeover, menus,
  media detection, video button), link picker. D56–D59.
- **M5 (2026-10-30):** tool manager (verified yt-dlp/FFmpeg installs with rollback), media
  engine via yt-dlp, quality picker, DRM refusal. D49–D55.
- **M4 (2026-10-30):** GUI, engine bridge, IPC + single instance, CLI over IPC. D42–D48.
  Manual steps 1-8 passed on the user's PC; fixed the squeezed name column and added the
  wizard's low-space warning from that run.
- **M3:** SQLite storage, encrypted secrets, DownloadManager (queues, host limits, schedules).
- **M2:** multi-connection engine, crash-safe resume, retries, fallbacks, limits, checksums.
- **M1:** errors, events, filename handling, probe, CLI. **M0:** tooling, test server, CI.

### Next
- User publishes the `v0.8.0-rc.1` draft as a pre-release and runs the M8 checklist
  (docs/TESTING.md); at step 7 Claude bumps to `0.8.0-rc.2` and pushes that tag.
- On approval: plan **M9 Hardening and public launch**.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager from the Terminal panel tab.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- Tools for tests: `D:\Tools\yt-dlp\yt-dlp.exe`, `D:\Tools\ffmpeg\bin\ffmpeg.exe`; set
  `OPENDM_TEST_TOOLS=D:\Tools`. The app's own tools folder is `D:\Projects\opendm\tools-bin`
  (git-ignored), set by the user in Settings -> Tools.
- Build: `scripts\build.cmd`; Inno Setup at `D:\Tools\InnoSetup\ISCC.exe`. In Git Bash pass
  `MSYS_NO_PATHCONV=1` to ISCC (its `/D` switches look like paths).
- Node for extension tests: `D:\Tools\node\node.exe --test extension\tests\logic.test.mjs
  extension\tests\manifest.test.mjs`.
- PowerShell 5.1 `Invoke-WebRequest` is unusably slow for big files; use `curl.exe`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- Offscreen Qt has no usable fonts on Windows; use `scripts/screenshots.py` for visual checks.
