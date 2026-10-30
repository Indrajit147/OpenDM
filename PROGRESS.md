# Progress

## Current milestone: M3 Storage, queue, scheduler (complete, awaiting user review)

### M3 done (2026-10-30)
- `storage/db.py`: SQLite (WAL, foreign keys), transactional numbered migrations tracked in
  `PRAGMA user_version`; `storage/migrations/0001_initial.sql` (queues, categories, jobs,
  settings; Main queue and six categories seeded).
- `storage/repositories.py`: jobs (history, search/filters, interrupted-recovery, safe deletes,
  redownload), queues, categories, settings. Cookies and auth headers are DPAPI-encrypted
  (`core/secrets.py`); without DPAPI they are not stored.
- `queue/scheduler.py` `DownloadManager`: add/start/pause/resume/restart/remove/refresh_link/
  redownload, per-queue concurrency, manual "start now", per-host connection sharing
  (`queue/host_limits.py`), global speed limit, schedule windows with `tick()` on an injectable
  clock (`queue/schedule.py`), `QueueFinished` event and after-queue action hook
  (`queue/power.py`, no-op until M4), progress saved to the DB every 2 s.
- `discovery/categories.py`: extension matching (longest extension wins) and category folders.
- `core/paths.downloads_dir()` (Known Folder API), `core/models` Job/Queue/Category.
- Decisions D35–D41.

### Results
- `pytest -q`: 406 passed (plus repeat runs). `ruff check .` / `ruff format --check .`: clean.
- Coverage 93% overall; every `core/`, `engine/`, `storage/`, `queue/` module >= 84%.
- Acceptance: jobs persist across restarts (incl. encrypted cookies; resumed download has the
  correct SHA-256 and re-fetches nothing beyond in-flight data); crash recovery marks running
  jobs "interrupted"; queue max_concurrent=2 holds with 5 jobs in order; per-host limit shares
  and waits correctly; schedule start/stop on a fake clock, after-action fires exactly once and
  never for a manually stopped or empty queue; global speed limit within +-10%.

### Known limitations
- No GUI or IPC yet (M4): the manager is used from tests only; sleep/shutdown is a no-op hook.
- Per-host limits are granted when a job starts; a running job does not gain connections when
  another finishes.
- Category is guessed from the URL name when a job is added; the M4 start dialog will show
  the probed name and let the user change it.
- TLS failure path still has no end-to-end test (no local HTTPS server).

### Earlier milestones
- **M2 (2026-10-30):** multi-connection engine (`HttpDownload`), crash-safe resume, retries,
  fallbacks, speed limit, checksums, CLI options. D27–D34.
- **M1 (2026-10-30):** errors, events, progress, filename sanitizer, Content-Disposition
  parsing, httpx transport, probe, CLI. D20–D26.
- **M0 (2026-10-30):** Python 3.12.10 at `D:\Tools\Python312`, repo skeleton, tooling, GPL-3.0,
  fault-injection test server, CI. D1–D19.

### Next
- User reviews M3.
- On approval: plan **M4 GUI v1** (needs approval for PySide6 and pytest-qt).

### Open questions
- None.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager. Pushing from a non-interactive
  shell fails; push from the Terminal panel tab instead.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- A refused TCP connection takes ~2 s on Windows (SYN retries); avoid repeating them in tests.
- PowerShell 5.1 `Set-Content -Encoding utf8` adds a BOM; prefer the Write/Edit tools.
- The user's Downloads folder is `C:\Users\Hp\Downloads`; tests never write there.
