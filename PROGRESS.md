# Progress

## Current milestone: M5 Tool manager + media engine (complete, awaiting user review)

### M5 done (2026-10-30)
- Tools for development/tests, verified and installed with the user's approval:
  yt-dlp 2026.10.26 (`D:\Tools\yt-dlp`, SHA2-256SUMS match) and FFmpeg 9.0.2 essentials
  (`D:\Tools\ffmpeg\bin`, gyan.dev SHA-256 match; only ffmpeg/ffprobe/LICENSE extracted).
- `engine/media/`: `process.py` (argument lists, no console, Windows Job Object kill-on-close),
  `ytdlp.py` (analysis `-J --flat-playlist`, shared options, manifest DRM check), `download.py`
  (`MediaDownload`, same interface as HttpDownload; pause = stop tree, resume = `--continue`),
  `formats.py`, `drm.py`, `cookies.py` (temporary Netscape file), `progress.py`.
- `tools/`: `sources.py` (official URLs), `manager.py` (status, latest release, verified install
  with backup and rollback, "use existing", update check).
- Schema v2 (`0002_media_jobs.sql`): job kind + media options. Manager: `analyze_media`,
  `add_media`, `install_tool`, `tool_status`, `check_ytdlp_update`, `configure_tools`.
- `discovery/classify.py`: file / manifest / page. IPC `add` accepts `media` options.
- CLI: `get --media [--quality 1080p|mp3|m4a] [--container] [--tools-dir]`, standalone or via app.
- GUI: start dialog hands pages/streams to the media flow; tool consent dialog (what, where from,
  size, folder, free space) + progress; quality picker (qualities, container, subtitles incl.
  automatic, thumbnail, folder, queue, playlist checklist); Settings -> Tools panel (versions,
  download/update, use existing, check now, opt-in weekly check); DRM and "no media" messages.
- Test server: `/static/` route and `--static` option. Fixtures script
  `scripts/make_media_fixtures.py`. Decisions D49–D55.

### Results
- `pytest -q` with `OPENDM_TEST_TOOLS=D:\Tools`: 604 passed. `ruff check .`/`format`: clean.
- Acceptance (real yt-dlp + FFmpeg, local fixtures): MP4, HLS and DASH (separate video/audio,
  merged by FFmpeg) download to MP4 with audio+video and ~5 s duration (ffprobe); audio-only
  MP3; subtitles to .srt; SAMPLE-AES HLS and Widevine DASH refused with "protected content is
  not supported"; pause/resume. Tool update from Settings: tested against a fake release
  (verified install, backup, rollback on bad checksum or broken binary) and in the GUI panel.
- Found and fixed: yt-dlp did not flag Widevine DASH as DRM -> OpenDM now checks manifests
  itself (D51); FFmpeg's DASH muxer wrote segments into the current folder (fixture script runs
  it in place).

### Known limitations
- FFmpeg has one source (gyan.dev); the BtbN fallback mentioned in the plan was not built.
- Checksums come from the same site as the tools (integrity, not an independent signature);
  yt-dlp's GPG signature is not verified.
- Real-tool tests do not run on CI (skipped without `OPENDM_TEST_TOOLS`).
- The global speed limit does not apply to media jobs (each gets yt-dlp's `--limit-rate`).
- Media progress has no segment map (yt-dlp reports one stream at a time).
- Windows notifications still say "Python" until the M7 installer.
- The user's manual checklists for M4 steps 9-14 and M5 have not been reported yet.

### Earlier milestones
- **M4 (2026-10-30):** GUI, engine bridge, IPC + single instance, CLI over IPC. D42–D48.
  Manual steps 1-8 passed on the user's PC; fixed the squeezed name column and added the
  wizard's low-space warning from that run.
- **M3:** SQLite storage, encrypted secrets, DownloadManager (queues, host limits, schedules).
- **M2:** multi-connection engine, crash-safe resume, retries, fallbacks, limits, checksums.
- **M1:** errors, events, filename handling, probe, CLI. **M0:** tooling, test server, CI.

### Next
- User runs the M5 manual checklist (docs/TESTING.md) and reviews.
- On approval: plan **M6 Browser extension + Native Messaging host**.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager from the Terminal panel tab.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- Tools for tests: `D:\Tools\yt-dlp\yt-dlp.exe`, `D:\Tools\ffmpeg\bin\ffmpeg.exe`; set
  `OPENDM_TEST_TOOLS=D:\Tools`. The app's own tools folder is `D:\Projects\opendm\tools-bin`
  (git-ignored), set by the user in Settings -> Tools.
- PowerShell 5.1 `Invoke-WebRequest` is unusably slow for big files; use `curl.exe`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- Offscreen Qt has no usable fonts on Windows; use `scripts/screenshots.py` for visual checks.
