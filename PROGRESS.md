# Progress

## Current milestone: M1 Single-stream engine + CLI (complete, awaiting user review)

### M1 done (2026-10-30)
- `core/`: error model (`errors.py`), data models, events, speed/ETA meter, unit formatting,
  redaction of URLs/headers, Windows-safe filename sanitizer (`filenames.py`).
- `discovery/content_types.py`: own Content-Type -> extension table.
- `engine/http/`: httpx `transport.py` (URL validation, error translation),
  `disposition.py` (RFC 6266/5987, lenient), `naming.py` (CD -> final URL -> content type),
  `probe.py` (HEAD, fallback to `GET Range: bytes=0-0`), `single.py` (single-stream download,
  `.odm-part` + rename, SHA-256 while streaming, disk-space check, in-session pause/resume
  with Range + If-Range, cancel).
- `cli/__main__.py`: `opendm-cli get <url> --standalone` with live progress; `opendm-cli.exe`
  entry point.
- Decisions D20–D26 recorded (M1 defaults approved by the user).

### Results
- `pytest -q`: 257 passed. `ruff check .` / `ruff format --check .`: clean.
- Coverage: 91% overall; every `core/` and `engine/` module >= 87% except `core/paths.py`
  (81%, frozen-exe branch only runs in M7 builds).
- Real run of `opendm-cli.exe`: 100 MiB from the test server in ~1 s, SHA-256 matches;
  Bangla filename from Content-Disposition saved correctly; Ctrl+C prints "cancelled" and
  leaves no partial file.

### Known limitations (by design until later milestones)
- One connection only; `-c N` prints a note (M2).
- Pause/resume works only within one process; no state sidecar, so no resume after a crash (M2).
- No automatic retries; errors are classified `retryable` for M2's retry loop.
- No checksum option yet (M2). TLS failure path not covered by an automated test (no local
  HTTPS server); classification is unit-tested via the exception chain.
- `opendm-cli list/pause/resume/remove` and IPC mode need the app (M4).

### M0 done (2026-10-30)
- Python 3.12.10 at `D:\Tools\Python312`; venv `.venv`; pip cache `D:\pipcache`.
- Repo skeleton, tooling, GPL-3.0 LICENSE (D19), branding/paths, fault-injection test server,
  CI on `windows-latest`, docs (README, CLAUDE.md, DECISIONS, TESTING, licenses).

### Next
- User reviews M1 and the manual checklist in `docs/TESTING.md`.
- On approval: plan **M2 Multi-connection engine**.

### Open questions
- None.

### Environment notes
- No `gh` CLI; pushes use plain `git` via Git Credential Manager. Pushing from a non-interactive
  shell fails; push from the Terminal panel tab instead.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
- On Windows `time.monotonic()` ticks every ~15.6 ms; timing tests use `perf_counter` + slack.
- A refused TCP connection takes ~2 s on Windows (SYN retries); avoid repeating them in tests.
