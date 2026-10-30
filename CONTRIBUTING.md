# Contributing to OpenDM

Thanks for helping. Bug reports, tested fixes, translations and documentation are all welcome.

## Reporting a bug

Open an [issue](https://github.com/Indrajit147/OpenDM/issues/new/choose) with the bug form.
Attach an *Export diagnostics* ZIP (Settings -> General): it contains OpenDM's logs and
settings with links, cookies and passwords removed. Security problems go privately through
[SECURITY.md](docs/SECURITY.md), not in a public issue.

## Ground rules

- **Legal:** OpenDM never circumvents DRM, paywalls, logins or CAPTCHAs, and contributions
  that do will not be accepted. Write code yourself (clean room); do not copy from other
  download managers. Keep "IDM"/"Internet Download Manager" out of names, logos and the UI.
- **Licence:** contributions are under GPL-3.0-or-later, like the rest of OpenDM. New
  dependencies must have a compatible licence and be listed in
  [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md); please ask in an issue before adding one.
- **No telemetry**, no ads, no network calls the user did not ask for.
- **No secrets** in the repository (tokens, cookies) and no large binaries or generated files.

## Setting up (Windows, CMD)

You need Python 3.12 (64-bit). Node.js 20+ for the extension tests, and Inno Setup 6 only to
build the installer.

```
git clone https://github.com/Indrajit147/OpenDM.git
cd OpenDM
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest -q
```

Run the app from source with `.venv\Scripts\opendm.exe`. Tests use a local test server
(`tests/server/`), never the internet; tests marked `live` are skipped by default. Video
tests with the real yt-dlp and FFmpeg run when `OPENDM_TEST_TOOLS` points at a folder with
`yt-dlp\yt-dlp.exe` and `ffmpeg\bin\ffmpeg.exe`. More in [docs/TESTING.md](docs/TESTING.md).

## Making a change

1. Open an issue first for anything bigger than a small fix, so we agree on the approach.
2. Write the test first, then the code. Keep the GUI thread free of network and disk-heavy
   work (the engine runs on its own thread).
3. Before you push:
   ```
   .venv\Scripts\ruff.exe check .
   .venv\Scripts\ruff.exe format .
   .venv\Scripts\python.exe -m pytest -q
   ```
   and for extension changes `node --test extension/tests/logic.test.mjs extension/tests/manifest.test.mjs`.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) (`fix(media): ...`,
   `feat(gui): ...`, `docs: ...`) and add a line to [CHANGELOG.md](CHANGELOG.md) for
   anything users notice.
5. Open a pull request; CI runs lint and all tests on Windows. Architectural choices are
   recorded in [docs/DECISIONS.md](docs/DECISIONS.md).

## Translations

All UI text goes through Qt's `tr()`. Translations (Bangla first) are planned; open an issue
if you would like to help.

By contributing you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
