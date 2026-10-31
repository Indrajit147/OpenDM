# Progress

## Current milestone: M10 part 1 - Edge Add-ons, code signing, GitHub settings (prepared)

### Done (2026-10-31)
- Extension: the popup and options page tell apart "app not installed" (link to the latest
  release), "OpenDM does not know this extension yet" (update, then Repair) and "not
  running" (`extension/lib/status.js`, tested). Edge store ZIP from
  `scripts/package_extension.py`; Partner Center steps, certification notes and a 300 px logo
  in `store/`.
- Code signing: `scripts/build.py --stage programs|package`; the release workflow signs the
  programs and then the installer through SignPath once `SIGNPATH_ORGANIZATION_ID` is set
  (skipped until then). Application answers and SignPath setup in docs/CODE_SIGNING.md;
  README has a code signing policy section. D69-D70.
- docs/GITHUB_SETTINGS.md: 2FA, private vulnerability reporting, Dependabot, secret
  scanning, ruleset for main, About/topics.
- Not done, by decision: DRM circumvention (illegal, against spec section 2, SignPath and
  store rules). Chrome Web Store waits for the one-time fee.
- Tests: 775 Python, 14 extension; ruff clean.

- GitHub settings done by the user (2026-10-31): 2FA, security features, ruleset `main`
  (no deletion, no force push; checked via the API), About description, website and topics.

### Waiting on the user
- Publish the OpenDM 1.0.1 draft release (the Edge listing is already live and needs it).
- SignPath: reapply later (declined 2026-10-31 for low visibility, D71).

### Edge Add-ons (2026-10-31)
- OpenDM Integration is live on Edge Add-ons (CRX ID `bionffckkflcblecfgnclbndjflemgld`);
  OpenDM 1.0.1 allows it (release run green). README and INSTALL point Edge users there.

## Previous milestone: M9 Hardening and public launch (complete: 1.0.0)

### M9 done (2026-10-31)
- Logs without secrets and Settings -> General -> Export diagnostics (D67).
- Per-download certificate override after a certificate error, with a warning (D68).
- Moving the tools runs on a worker thread (no window freeze).
- Security review against spec 7: docs/SECURITY.md; rules as source-scanning tests; the IPC
  pipe's Windows permissions grant only the current user (tested).
- `scripts/perf_check.py`: 10 downloads, ~122 MB peak working set, window ping max 2 ms.
  Coverage engine + core 92%.
- Docs: README with screenshots, INSTALL, USER_GUIDE, FAQ, SECURITY, CODE_SIGNING,
  CONTRIBUTING, CODE_OF_CONDUCT, issue/PR templates; PRIVACY updated.
- Stores: `store/` listing, permission justifications, images; `scripts/package_extension.py`.
  Signing: options compared, SignPath Foundation recommended after 1.0. Installer privacy
  note.
- Version 1.0.0-rc.1, CHANGELOG [1.0.0]. rc.1 published and installed on the user's PC
  through the in-app update (logs and diagnostics checked there).
- The user approved the release: version 1.0.0, tag `v1.0.0` (2026-10-31). Release run green
  (5 min); the user published it as the latest release. The real update check offers 1.0.0
  to 0.8.0-rc.2 and 1.0.0-rc.1 (test versions off) and nothing newer to 1.0.0.

### Results
- `pytest` with real tools: 770 passed. Node: 13 passed. `ruff check`/`format`: clean.
- 1.0.0-rc.1 build: `smoke_dist.py` 14/14; `perf_check.py` idle 78 MB, 10 downloads peak
  123 MB working set / 85 MB private, window-thread ping max 2 ms, all 10 still running.
- Sizes: setup 27 MB, portable ZIP 45 MB. Store ZIP 32 KB.
- GitHub: CI green on 74df9bc (after fixing the new pipe test for the runner's built-in
  Administrator, listed as the alias LA). Release workflow for `v1.0.0-rc.1` green (5.5 min);
  the draft is waiting to be published by the user.

### Known limitations
- Unsigned builds (SmartScreen). YouTube videos that need a login need a JavaScript runtime
  for yt-dlp (proposed for M10). Store builds need their IDs added to `EXTENSION_IDS`.
- Four media modules are at 82-84% coverage (engine and core overall 92%).

### Earlier milestones
- **M8 (2026-10-31):** release workflow, opt-in updater (with releases-feed fallback), own
  tools folder, missing-tools wait, playlist links; rc.1 -> rc.2 update tested on the user's
  PC. D64-D66.
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
- M10 items, each with its own approval (spec): YouTube logins via a JavaScript runtime for
  yt-dlp, Firefox extension, Bangla translation, winget package, torrents, FTP/SFTP.
- Store IDs into `EXTENSION_IDS` once the extension is published.
- Programs started inside the Claude app see a private copy of the registry, so registry
  results are checked from outside it (TESTING.md).

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
