# Progress

## Current milestone: M0 Foundations (complete, awaiting user review)

### Done (2026-10-30)
- App name confirmed: **OpenDM** (`src/opendm/core/branding.py`).
- Python 3.12.10 installed at `D:\Tools\Python312` (python.org, per-user, not on PATH);
  venv at `.venv`; pip cache `D:\pipcache`.
- Repo skeleton per spec section 5; `pyproject.toml` (setuptools, ruff, pytest, coverage);
  `.gitignore`; GPL-3.0 LICENSE (replaced the MIT file GitHub created, see D19).
- `core/branding.py` and `core/paths.py` (app data dir, portable mode) with unit tests.
- Local fault-injection test server (`tests/server/`) covering every case in spec section 8,
  with integration tests.
- GitHub Actions CI on `windows-latest` (ruff + pytest + coverage).
- Docs: README, CLAUDE.md, DECISIONS.md (D1–D19), TESTING.md, THIRD_PARTY_LICENSES.md.

### Results
- `pytest -q`: 65 passed. `ruff check .` and `ruff format --check .`: clean.

### Next
- User reviews M0 and the manual checklist in `docs/TESTING.md`.
- On approval: plan **M1 Single-stream engine + CLI** (needs approval for the `httpx`
  dependency, BSD-3-Clause).

### Open questions
- Confirm the switch from MIT to GPL-3.0-or-later (spec requires GPL; D19).

### Environment notes
- No `gh` CLI on the machine; pushing uses plain `git` with Git Credential Manager.
- Python launcher `py` is not used; always call `D:\Tools\Python312\python.exe` or `.venv`.
