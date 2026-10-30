# Progress

## Current milestone: M7 Packaging (complete, awaiting user review)

### M7 done (2026-10-30)
- Installed with approval: PyInstaller 6.22.3 (venv, dev extra) and Inno Setup 6.7.4
  (`D:\Tools\InnoSetup`, per user; SHA-256 matched the GitHub release digest, Authenticode
  signature valid).
- Version 0.7.0 with one source (`opendm.__version__`). The app sets AppUserModelID
  `Indrajit147.OpenDM` and holds mutex `OpenDM-AppRunning` for the installer. `write_ico()` makes
  the program/installer icon from the drawn app icon.
- `installer/opendm.spec`: one folder with OpenDM.exe, opendm-cli.exe, opendm-host.exe (icons,
  version info; console programs without Qt; unused Qt parts dropped), licenses and the
  unpacked extension. `scripts/build.cmd` -> 88 MB folder, 45 MB portable ZIP, 26 MB setup.
- `installer/opendm.iss`: per-user install (folder choice, Start menu, optional desktop icon,
  Chrome/Edge registration, close-the-app check), upgrade cleanup, uninstaller that removes
  files/shortcuts/keys and asks before deleting user data.
- `opendm-host.exe --register|--unregister|--status` and Settings -> Browser (status, set up,
  remove, extension folder). IPC `quit` command.
- Decisions D60–D63.

### Results
- `pytest -q`: 657 passed, 8 skipped (real-tool tests); with `OPENDM_TEST_TOOLS=D:\Tools`: 665
  passed. Node: 13 extension tests passed. `ruff check .`/`format`: clean.
- `scripts/smoke_dist.py` (from the portable ZIP): 14/14 checks passed: CLI standalone download
  with the right SHA-256, host replies, GUI starts hidden in portable mode, answers through the
  host and the CLI, keeps data next to the exe, quits cleanly.
- `scripts/installer_test.py`: 38/38 checks passed: silent install to `build\install-test`,
  files, Start menu shortcut, uninstall entry, manifest + Chrome/Edge keys, installed CLI and
  host run; reinstall (upgrade path); uninstall leaves no files, shortcut, uninstall entry or
  browser keys; `%LOCALAPPDATA%\OpenDM` untouched; dev registration restored.

### Known limitations
- Unsigned builds: SmartScreen warns. Signing options are part of M8.
- Not tested on a second Windows account (Windows 11 Home has no Windows Sandbox): manual step.
- The desktop shortcut and the "close OpenDM first" prompt are covered only by the manual
  checklist.
- Builds are made locally; CI builds and releases come with M8.
- The user's manual checklists for M4 steps 9-14, M5, M6 and M7 have not been reported yet.

### Earlier milestones
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
- User runs the M7 manual checklist (docs/TESTING.md) and reviews.
- On approval: plan **M8 Release pipeline + updater**.
- Also in M8 (user request, 2026-10-30): yt-dlp/FFmpeg go in their own folder chosen at install
  time (installer: next to the app's data, e.g. `%LOCALAPPDATA%\OpenDM\tools`; portable: `data\tools`),
  never in Downloads, so cleaning Downloads cannot remove them. Existing installs with tools in
  Downloads get moved. Also: if tools go missing, offer to reinstall them instead of failing every
  job; report a missing yt-dlp.exe as "yt-dlp is not installed"; a video link inside a Mix/playlist
  defaults to that one video.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager from the Terminal panel tab.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- Tools for tests: `D:\Tools\yt-dlp\yt-dlp.exe`, `D:\Tools\ffmpeg\bin\ffmpeg.exe`; set
  `OPENDM_TEST_TOOLS=D:\Tools`. The app's own tools folder is `D:\Projects\opendm\tools-bin`
  (git-ignored), set by the user in Settings -> Tools.
- Build: `scripts\build.cmd`; Inno Setup at `D:\Tools\InnoSetup\ISCC.exe`. In Git Bash pass
  `MSYS_NO_PATHCONV=1` to ISCC (its `/D` switches look like paths).
- Node for extension tests: `D:\Tools\node\node.exe --test extension\tests\`.
- PowerShell 5.1 `Invoke-WebRequest` is unusably slow for big files; use `curl.exe`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- Offscreen Qt has no usable fonts on Windows; use `scripts/screenshots.py` for visual checks.
