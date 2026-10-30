# Testing

## Automated tests (CMD, from `D:\Projects\opendm`)

```
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

With coverage: `.venv\Scripts\python.exe -m pytest -q --cov --cov-report=term-missing`.
Tests marked `live` (real internet) are skipped by default; run them with `-m live`.

Layout: `tests/unit/` (pure logic), `tests/integration/` (against the local test server),
`tests/gui/` (pytest-qt, from M4), `tests/server/` (the test server), `tests/fixtures/`
(generated, git-ignored).

Temporary test files go to `build\pytest-tmp` (set by `--basetemp` in `pyproject.toml`), not to
`%TEMP%` on C:. Pytest empties that folder at the start of each run. The full suite downloads
about 250 MB there, including a 100 MiB kill-and-resume test that starts the CLI as a separate
process.

## Local test server

`tests/server/app.py`, stdlib only. Tests use the `server` fixture from `tests/conftest.py`
(random free port, fault state reset per test). All routes and parameters are documented in
the module docstring, which the server also prints at startup.

| Fault case (spec section 8) | Example path |
|---|---|
| Range supported | `/file/a.bin?size=100M` |
| Range unsupported | `/file/a.bin?range=none` |
| 200 instead of 206 | `/file/a.bin?range=ignore` |
| No Content-Length | `/file/a.bin?length=none` (or `length=chunked`) |
| UTF-8 Content-Disposition | `/file/x?cd=রিপোর্ট.pdf&cd_mode=both` (`ext`, `plain`, `raw`) |
| Redirects | `/redirect/3?to=/file/a.bin` |
| Throttling | `/file/a.bin?rate=500K` |
| Connection drop at byte N | `/file/a.bin?drop_at=5000000` |
| ETag change mid-download | `/file/a.bin?etag_after=1` |
| 403 after N seconds | `/file/a.bin?expire_after=10` |
| Slow start | `/file/a.bin?slow_start=3` |
| gzip encoding | `/file/a.bin?gzip=1` |
| Cookie-protected route | `/protected/a.bin` (cookie from `/set-cookie`) |
| 404 / 500 | `/status/404`, `/status/500` |
| HEAD fails / lies | `/file/a.bin?head=fail`, `head=lie`, `head=nolength` |
| First N requests fail | `/file/a.bin?fail_first=3` |
| Connection limit | `/file/a.bin?max_conn=4&retry_after=1` (503 beyond 4 parallel requests) |

## Manual checklist: M0

1. Open CMD and run:
   ```
   cd /d D:\Projects\opendm
   .venv\Scripts\python.exe -m tests.server
   ```
   Expect `Serving on http://127.0.0.1:8765` and the route list.
2. In a browser, open `http://127.0.0.1:8765/file/test.bin?size=5M&cd=hello.zip&cd_mode=plain`.
   The browser downloads `hello.zip` (5 MiB).
3. Open `http://127.0.0.1:8765/file/slow.bin?size=5M&rate=500K`. The download takes about 10 s.
4. Open `http://127.0.0.1:8765/protected/p.bin?size=1K`. Expect "cookie required".
   Open `http://127.0.0.1:8765/set-cookie`, then the protected link again: it downloads.
5. Open `http://127.0.0.1:8765/file/x.bin?size=1K&cd=রিপোর্ট.pdf`. The saved name is `রিপোর্ট.pdf`.
6. Press Ctrl+C in CMD. The server stops.
7. Check the CI run at https://github.com/Indrajit147/OpenDM/actions is green.

## Manual checklist: CLI (M1 + M2)

Keep the test server from the M0 checklist running in one CMD window. In a second CMD window:

```
cd /d D:\Projects\opendm
mkdir build\manual
```

1. 100 MiB over 8 connections:
   ```
   .venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/file/big.bin?size=100M&seed=9" -o build\manual --standalone
   ```
   Expect a live line such as `45.0%  45.0 MiB / 100.0 MiB  ...  8 conn  ETA 0:01`, then
   `SHA-256: 3dc090164912e6fff05772f82494ba9ae508e44577f1fe4b8b3499dbae117684`.
2. UTF-8 filename:
   ```
   .venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/file/x?size=1K&cd=%E0%A6%B0%E0%A6%BF%E0%A6%AA%E0%A7%8B%E0%A6%B0%E0%A7%8D%E0%A6%9F.pdf" -o build\manual --standalone
   ```
   In Explorer, `build\manual` contains `রিপোর্ট.pdf`.
3. Run command 1 again. The new file is `big (1).bin`; `big.bin` is untouched.
4. Pause with Ctrl+C, then resume:
   ```
   .venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/file/slow.bin?size=50M&rate=1M" -o build\manual --standalone
   ```
   After ~5 s press Ctrl+C: expect `paused - run the same command again to resume`, and
   `slow.bin.odm-part` + `slow.bin.odm-state` in `build\manual`. Run the same command again:
   the percentage continues from where it stopped and the download completes.
5. Kill and resume: start command 4 again with a new name (`slow2.bin` in the URL), and after a
   few seconds end `opendm-cli.exe` in Task Manager (End task). Run the command again: it
   resumes, and the final SHA-256 is printed.
6. Speed limit: add `--limit 500K` to command 4 (new name `slow3.bin`): the speed shows about
   `500.0 KiB/s`.
7. Checksum: add `--sha256 0000000000000000000000000000000000000000000000000000000000000000` to
   command 1: expect `[checksum_mismatch]` and exit code 1 (`echo %ERRORLEVEL%`).
8. Errors (each prints `error: ... [kind]`):
   - `.venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/status/404" --standalone` -> `[not_found]`
   - `.venv\Scripts\opendm-cli.exe get "ftp://example.com/a.zip" --standalone` -> `[unsupported_scheme]`
   - `.venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/file/c.bin?size=5M&etag_after=1" -o build\manual --standalone`
     -> `[validator_changed]` with a `--restart` hint
9. Fallbacks: `.../file/n.bin?size=20M&range=none` and `.../file/i.bin?size=20M&range=ignore`
   both complete; the second prints no error (it switches to one connection).
10. Real internet (optional):
    `.venv\Scripts\opendm-cli.exe get "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -o build\manual --standalone --md5 5eddb0b6f12c852725de071ae681dde4`
11. Clean up: `rmdir /s /q build\manual`.

## Manual checklist: M3

M3 has no user-facing surface yet (the GUI arrives in M4), so it is verified by the automated
tests: `tests/unit/test_db.py`, `test_repositories.py`, `test_categories_schedule.py` and
`tests/integration/test_manager.py` (restart, crash recovery, queue concurrency, host limits,
schedules with a fake clock). Optional check that secrets are encrypted at rest:

1. Run `.venv\Scripts\python.exe -m pytest -q tests\unit\test_repositories.py -k encrypted`.
2. It writes a database with a cookie, then searches the raw database file for the cookie text;
   the test passes only if the text is not found.
