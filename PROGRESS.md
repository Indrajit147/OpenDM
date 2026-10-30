# Progress

## Current milestone: M6 Browser extension + Native Messaging host (complete, awaiting user review)

### M6 done (2026-10-30)
- Node.js 26.13.0 LTS for the extension tests, installed with approval to `D:\Tools
ode`
  (SHA-256 verified). Dev-only; the extension has no npm dependencies.
- `host/`: Native Messaging framing (`protocol.py`), relay to the app over the pipe with
  start-and-wait when the app is not running (`relay.py`), `python -m opendm.host`.
- IPC commands `capture` and `capture_links`. The app opens the start dialog (with cookies,
  referrer and user agent), the quality picker for `media`, or a new link picker dialog
  (category and text filter; files pre-checked, pages not).
- `extension/` (MV3, Chrome and Edge, fixed ID `pjkejmcidaikllfpgmfginpahcockofb`): takeover,
  Alt+click skip, context menus (link, video/audio, page video, all links), media detection
  with badge, video button, popup (status, detected media, page video) and options page.
- `scripts/register_host_dev.cmd` / `unregister_host_dev.cmd`: registered on this PC for
  Chrome and Edge (HKCU), verified with a framed status message through the launcher.
- Test server `/pages/` with checklist pages (links, video, stream). CI runs the Node tests.
- docs/PRIVACY.md (data flows and every permission). Decisions D56–D59.

### Results
- `pytest -q`: 635 passed, 8 skipped (real-tool tests); with `OPENDM_TEST_TOOLS=D:\Tools`:
  643 passed. Node: 13 extension tests passed. `ruff check .`/`format`: clean.
- End to end without a browser: a real host subprocess relays to a test IPC server; cookie-
  protected download completes through capture -> start dialog; without the cookie the dialog
  shows HTTP 403; app-not-running answers "unavailable" so the extension can resume.
- Found and fixed: capture tests could pick up a start dialog left open by another test.

### Known limitations
- The extension itself (takeover, menus, detection) is only tested by hand; the manual M6
  checklist in docs/TESTING.md has not been run in Chrome or Edge yet.
- Alt+click opens a 3 s window in which any new download stays in the browser.
- MV3 cannot read response bodies, so media detection relies on headers and URLs.
- Not in a web store; load unpacked. The installer (M7) will register `opendm-host.exe`.
- From M5: one FFmpeg source; real-tool tests not on CI; notifications say "Python" until M7.
- The user's manual checklists for M4 steps 9-14, M5 and M6 have not been reported yet.

### Earlier milestones
- **M5 (2026-10-30):** tool manager (verified yt-dlp/FFmpeg installs with rollback), media
  engine via yt-dlp, quality picker, DRM refusal. D49–D55.
- **M4 (2026-10-30):** GUI, engine bridge, IPC + single instance, CLI over IPC. D42–D48.
  Manual steps 1-8 passed on the user's PC; fixed the squeezed name column and added the
  wizard's low-space warning from that run.
- **M3:** SQLite storage, encrypted secrets, DownloadManager (queues, host limits, schedules).
- **M2:** multi-connection engine, crash-safe resume, retries, fallbacks, limits, checksums.
- **M1:** errors, events, filename handling, probe, CLI. **M0:** tooling, test server, CI.

### Next
- User runs the M6 manual checklist (docs/TESTING.md) in Chrome and Edge and reviews.
- On approval: plan **M7 Installer + portable build**.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager from the Terminal panel tab.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- Tools for tests: `D:\Tools\yt-dlp\yt-dlp.exe`, `D:\Tools\ffmpeg\bin\ffmpeg.exe`; set
  `OPENDM_TEST_TOOLS=D:\Tools`. The app's own tools folder is `D:\Projects\opendm\tools-bin`
  (git-ignored), set by the user in Settings -> Tools.
- Node for extension tests: `D:\Tools
ode
ode.exe --test extension	ests\`.
- PowerShell 5.1 `Invoke-WebRequest` is unusably slow for big files; use `curl.exe`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- Offscreen Qt has no usable fonts on Windows; use `scripts/screenshots.py` for visual checks.
