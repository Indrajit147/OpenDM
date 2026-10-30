# Progress

## Current milestone: M2 Multi-connection engine (complete, awaiting user review)

### M2 done (2026-10-30)
- `engine/http/download.py` `HttpDownload` replaces M1's `SingleStreamDownload`:
  up to 32 connections (default 8), dynamic splitting, preallocated `.odm-part` with positioned
  writes, crash-safe `.odm-state` checkpoints (fsync data, then atomic state) every 2 s and on
  pause/exit/failure, `.odm-lock` OS lock against a second process, retries with backoff and
  Retry-After, adaptive connection count when the server answers 429/503, fallback to one
  connection for no-Range and 200-instead-of-206 servers, VALIDATOR_CHANGED detection with
  `restart()`, `refresh(new_url)` for expired links, speed limit (per download + global bucket),
  checksum verification, SHA-256 computed at the end.
- New modules: `planner.py`, `writer.py`, `resume.py`, `ratelimit.py`, `retry.py`,
  `core/settings.py`, `core/checksum.py`; `core/units.parse_size`.
- CLI: `-c` (default 8), `--limit`, `--sha256/--sha1/--md5`, `--restart`, `--continue PART`;
  re-running the same command resumes; Ctrl+C pauses (exit 130).
- Test server: `fail_first`, `max_conn` + `retry_after`, `stats(path)`.
- Tests write to `build/pytest-tmp` (pytest `--basetemp`) so nothing lands on C:.
- Decisions D27–D34.

### Results
- `pytest -q`: 334 passed. `ruff check .` / `ruff format --check .`: clean.
- Acceptance: 100 MiB over 8 connections (peak 8 parallel requests seen by the server, SHA-256
  correct); hard kill (TerminateProcess) of the CLI mid-download, rerun resumes and fetches
  only the missing bytes, SHA-256 correct; no-Range and 200-instead-of-206 fall back; ETag change
  detected; speed limit 3 MiB at 1 MiB/s took 3.0-3.2 s (within +-10%).

### Known limitations
- Per-host connection limits across several downloads, queues and persistence of requests
  (cookies/headers for later resume) come in M3; the state file deliberately stores neither.
- SHA-256 is computed after the download by reading the file back (~1-2 s per GB on an SSD).
- A checksum mismatch keeps the file under its final name (decision D30).
- TLS failure path still has no end-to-end test (no local HTTPS server).
- `opendm-cli list/pause/resume/remove` need the app (M4).

### Earlier milestones
- **M1 (2026-10-30):** errors, events, progress, filename sanitizer, Content-Disposition
  parsing, httpx transport, probe, single-stream engine (now replaced), CLI. D20–D26.
- **M0 (2026-10-30):** Python 3.12.10 at `D:\Tools\Python312`, repo skeleton, tooling, GPL-3.0,
  fault-injection test server, CI. D1–D19.

### Next
- User reviews M2 and the manual checklist in `docs/TESTING.md`.
- On approval: plan **M3 Storage, queue, scheduler**.

### Open questions
- None.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager. Pushing from a non-interactive
  shell fails; push from the Terminal panel tab instead.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- A refused TCP connection takes ~2 s on Windows (SYN retries); avoid repeating them in tests.
- PowerShell 5.1 `Set-Content -Encoding utf8` adds a BOM; prefer the Write/Edit tools.
