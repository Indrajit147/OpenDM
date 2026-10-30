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
