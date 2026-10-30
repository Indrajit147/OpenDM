# CLAUDE.md: working rules for OpenDM

The full specification is `docs/PROJECT_SPEC.md` and is the source of truth.
If anything conflicts with it or seems wrong: **stop and ask**, never silently deviate.
Read `PROGRESS.md` at the start of every session.

## Project in one line
Free, open-source (GPL-3.0-or-later) Windows download manager: Python 3.12 + PySide6 GUI,
CLI, MV3 browser extension via Native Messaging, yt-dlp/FFmpeg for media.

## Legal ground rules (spec section 2)
- Clean-room only: public specs (RFC 9110, 6266, 5987, 8216, DASH docs, MDN, Chrome docs,
  yt-dlp/FFmpeg docs). Never decompile/inspect IDM or any commercial download manager.
- No "IDM"/"Internet Download Manager" in names, icons or UI. Original or openly licensed assets.
- No DRM circumvention, decryption, paywall/login bypass or CAPTCHA solving. Detect protected
  content and show "protected content is not supported".
- Verify every dependency's license; record it in `THIRD_PARTY_LICENSES.md`.

## Environment (spec section 3)
- Windows 11. Give the user **CMD** commands (PowerShell only if CMD cannot, and say so).
- **Keep everything off C:.** Repo `D:\Projects\opendm`, venv `.venv`,
  Python `D:\Tools\Python312`, `PIP_CACHE_DIR=D:\pipcache`, tools in `D:\Tools\<name>`.
  PyInstaller build/work dirs inside the repo, never `%TEMP%`.
- **Ask before any download, install or new Python/npm dependency**: what, why, size, folder.
- GitHub: https://github.com/Indrajit147/OpenDM. The user wants it kept up to date: push after
  each completed, green piece of work. No `gh` CLI; use plain `git`.

## Architecture rules (spec section 5)
- `core/` and `engine/` never import Qt. GUI never does network or disk-heavy work.
- All engine <-> GUI traffic goes through `core/bridge.py`.
- App name and derived IDs live only in `src/opendm/core/branding.py`.
- Security: no `shell=True`; subprocess args as lists; sanitize filenames; validate every IPC
  and Native Messaging message; TLS verification on by default; never log cookies/auth.

## Workflow for every milestone (spec section 10)
1. Plan: goals, files, interfaces, edge cases, acceptance tests, new deps (name, license,
   size, why), downloads (ask for path).
2. Wait for the user's approval.
3. Tests first for engine logic, then implement in small steps.
   Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `ci:`), one logical change each.
4. Run and read: `.venv\Scripts\python.exe -m pytest -q` and `.venv\Scripts\ruff.exe check .`
   (+ `ruff format --check .`). Never claim something works without running it.
   Anything not testable automatically goes on the manual checklist in `docs/TESTING.md`.
5. Report: what was built, test results, failures, decisions, known limitations.
6. Update `PROGRESS.md`, `docs/DECISIONS.md` and user docs.
7. Stop. Never start the next milestone without explicit approval.

## Testing
- Local fault-injection server: `tests/server/app.py` (routes documented in its docstring;
  run manually with `.venv\Scripts\python.exe -m tests.server`). Fixture: `server` in
  `tests/conftest.py`.
- No internet in default tests; real-site tests use `@pytest.mark.live` (skipped by default).
- pytest temp files go to `build/pytest-tmp` (`--basetemp`), never `%TEMP%` on C:.
- Coverage target >= 85% for `engine/` and `core/`.
- Never commit secrets, cookies, large binaries or generated fixtures (`tests/fixtures/`).

## Style
Simple, readable code; docstrings and type hints (mypy-friendly); ruff line length 100.
