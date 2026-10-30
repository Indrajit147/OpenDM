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

## Manual checklist: M4 (desktop app)

GUI tests run offscreen (`QT_QPA_PLATFORM=offscreen`, set in `tests/conftest.py`).
`.venv\Scripts\python.exe scripts\screenshots.py` renders the main window, details window and
start dialog with live downloads into `build\screens` without showing anything.

Keep the test server running in one CMD window (M0 checklist, step 1). In a second window:

Two things to know first:
- **Copy** the test links (select the text, Ctrl+C) and paste them into OpenDM. Do not open
  them in a browser: the browser would download the file itself.
- Test-server files are random bytes with real-looking names. Windows cannot open the
  "zip" or "pdf" files; that is expected. Delete them when you are done.

1. Start the app: `cd /d D:\Projects\opendm` then `.venv\Scripts\opendm.exe`.
   The first-run wizard appears. Choose a download folder on D: (for example `D:\Downloads`);
   the wizard warns in orange if the drive is nearly full. Keep the tools folder, finish.
   The main window opens; the tray shows the OpenDM icon.
   (App data lives in `%LOCALAPPDATA%\OpenDM`: a small database only.)
   Already ran the wizard with C:? Change it in **Settings -> General -> Download folder**.
2. Copy `http://127.0.0.1:8765/file/test-pack.zip?size=50M&rate=2M` and click **Add URL**: the
   link is already filled in. OK -> the start dialog shows `test-pack.zip`, 50.0 MiB, category
   Compressed, folder `D:\Downloads\Compressed`. Click **Start now**.
3. Watch the row: progress bar, speed, time left. Double-click it: the details window shows
   the speed graph and the segment map filling in 8 places. Click **Pause**, then **Resume**.
4. When it completes, a notification appears. Right-click the row: **Open folder** opens
   Explorer at the file.
5. **Add URL** -> **Batch** tab, paste `http://127.0.0.1:8765/file/part[1-3].bin?size=5M` ->
   "3 link(s)" -> OK. Three downloads start in `D:\Downloads` (category Other).
6. Sidebar: click **Finished**, **Compressed**, **Main**; type `part` in the search box.
7. Select a finished row, press Delete, tick "Also delete the downloaded file(s)", Yes: the row
   and the file disappear.
8. **Settings** -> Appearance -> Dark -> OK: the window turns dark. Set it back to "Same as
   Windows".
9. **Queues**: set "Start at" to two minutes from now, OK... (optional) add a download with
   "Add to queue" and see it start at that time. Set "When finished" to Shut down only if you
   want to see the 60 s countdown - press **Cancel** in it.
10. Close the window with X: a notice says OpenDM keeps running in the tray. Click the tray
    icon: the window returns.
11. CLI talking to the running app, in the second CMD window:
    `.venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/file/cli.bin?size=5M"` -> "Added ...",
    the row appears in the window; `.venv\Scripts\opendm-cli.exe list` shows it.
12. Start `.venv\Scripts\opendm.exe "http://127.0.0.1:8765/file/second.zip?size=1M"` while the
    app runs: no second window; the running app shows a start dialog for `second.zip`.
13. Drag a link from a browser's address bar onto the window: a start dialog opens.
14. Tray icon -> **Quit**. Start the app again: finished downloads are still listed.

## Media tests and manual checklist: M5 (video and audio)

Automated: `tests/unit/test_media_logic.py`, `tests/integration/test_media_fake.py` (fake yt-dlp,
runs everywhere), `test_tools.py` (fake GitHub release), `tests/gui/test_media_gui.py`, and the
real-tool acceptance tests `tests/integration/test_media_real.py`:

```
set OPENDM_TEST_TOOLS=D:\Tools
.venv\Scripts\python.exe -m pytest -q tests\integration\test_media_real.py
```

They generate the fixtures on first use (or run
`.venv\Scripts\python.exe scripts\make_media_fixtures.py D:\Tools\ffmpeg\bin\ffmpeg.exe`).

Manual checklist (needs the fixtures above). In CMD window 1, start the test server with the
media files:

```
cd /d D:\Projects\opendm
.venv\Scripts\python.exe -m tests.server --static tests\fixtures\media
```

In window 2, quit OpenDM from its tray menu and start it again (`.venv\Scripts\opendm.exe`).

1. **Settings -> Tools**: set the Tools folder to `D:\Projects\opendm\tools-bin`, OK. Open
   Settings -> Tools again: both tools say "Not installed (expected at ...tools-bin...)".
2. Copy `http://127.0.0.1:8765/static/page.html` -> **Add URL** -> OK. OpenDM sees a web page
   and asks to download the helper tools: yt-dlp (~22.5 MiB, github.com) and FFmpeg (~109.5 MiB,
   gyan.dev), folder `tools-bin`. Click **Download**; a progress window shows both downloads.
3. The quality picker opens: title "OpenDM test video", subtitle `en`. Tick `en`, keep MP4,
   **Start now**. The row completes; the folder (Video category) has the `.mp4` and an `.srt`.
   Open the video: 5 s colour bars with a tone.
4. **Add URL** `http://127.0.0.1:8765/static/dash/manifest.mpd` -> quality **Audio only (MP3)** ->
   Start: an `.mp3` appears in the Audio folder (FFmpeg merged/converted it).
5. **Add URL** `http://127.0.0.1:8765/static/dash_drm/manifest.mpd`: a message says protected
   content is not supported; nothing is downloaded.
6. **Settings -> Tools**: both tools show versions; **Check for yt-dlp update now** says it is up
   to date (or names a newer version).
7. CLI through the app:
   `.venv\Scripts\opendm-cli.exe get "http://127.0.0.1:8765/static/hls/index.m3u8" --media --quality 720p`
   -> "Added ..."; the row completes in the window.
8. Optional, real website: Add URL with a video page you are allowed to download (for example
   a Creative Commons video) and pick a quality.
9. Clean up the test files from your download folder.

## Extension tests and manual checklist: M6 (browser integration)

Automated: `D:\Tools\node\node.exe --test extension\tests\` (pure logic and manifest checks, no
npm packages; CI runs them with the runner's Node). The native host and the app's capture
handling are covered by pytest (`tests/unit/test_native_host.py`, `tests/gui/test_native_host_e2e.py`,
`tests/gui/test_capture.py`).

Setup (CMD, from `D:\Projects\opendm`):

1. Register the native host (once; writes `build\native-host\` and HKCU keys for Chrome and
   Edge; undo with `scripts\unregister_host_dev.cmd`):
   `scripts\register_host_dev.cmd`
2. Window 1, test server with the media fixtures (needs `make_media_fixtures.py` from M5):
   `.venv\Scripts\python.exe -m tests.server --static tests\fixtures\media`
3. Window 2: `.venv\Scripts\opendm.exe`
4. Chrome: `chrome://extensions` (Edge: `edge://extensions`) -> Developer mode on -> **Load
   unpacked** -> `D:\Projects\opendm\extension`. The ID must be `pjkejmcidaikllfpgmfginpahcockofb`.
   Pin the OpenDM toolbar button.

Checks (pages are under `http://127.0.0.1:8765/pages/`):

1. **Popup**: click the toolbar button: "Connected". Quit OpenDM from the tray: reopening the popup
   says "App not running". Start OpenDM again.
2. **Takeover** (`links.html`): click `archive.zip`. The browser download disappears and the
   OpenDM start dialog opens with `archive.zip`, 20 MB. Start it; it completes.
3. **Size and type rules**: `small.zip` (200 KB) and `notes.txt` stay in the browser.
4. **Alt+click** `setup.exe`: the browser keeps it.
5. **Cookie-protected file**: click `secret.zip` without the cookie: the start dialog shows HTTP
   403. Click "Set the test cookie", then `secret.zip` again: the dialog shows the size and the
   download completes.
6. **Context menu**: right-click `a.zip` -> **Download with OpenDM**: the start dialog opens.
7. **All links**: right-click the page -> **Download all links with OpenDM**: a list opens with
   the files pre-checked (a.zip once, b.mp4, c.mp3, archive.zip ...), `video.html` unchecked,
   no mailto link. Filter by Video; Download the checked ones.
8. **Video button** (`video.html`): hover the video: a "Download" button appears top right.
   Click it: the start dialog opens for `clip.mp4`. Right-click the video -> **Download with
   OpenDM** does the same. Turn the button off in the extension options, reload: no button.
9. **Media detection** (`stream.html`): the toolbar button shows a badge "1"; the popup lists
   "Stream: index.m3u8" (no `.ts` segment). Click its Download: the OpenDM quality picker opens
   for the page. "Download this page's video" on `video.html` does the same.
10. **App not running**: quit OpenDM, click `archive.zip`: OpenDM starts (minimized) and the
    start dialog appears within a few seconds. Then unregister (`scripts\unregister_host_dev.cmd`),
    restart the browser, click `archive.zip`: the browser downloads it itself and a
    notification says OpenDM is not available. Register again afterwards.
11. Repeat 2, 5 and 9 in Edge.
12. Clean up the test files from your download folder.

## Build tests and manual checklist: M7 (installer and portable build)

Build and automated checks (CMD, from `D:\Projects\opendm`; Inno Setup in `D:\Tools\InnoSetup`):

```
scripts\build.cmd
.venv\Scripts\python.exe scripts\smoke_dist.py
.venv\Scripts\python.exe scripts\installer_test.py
```

`build.cmd` writes `dist\OpenDM\`, `dist\OpenDM-<version>-portable.zip` and
`dist\OpenDM-<version>-setup.exe`. `installer_test.py` must run while OpenDM is **not**
installed; it re-registers the dev browser host at the end.

Manual checklist (quit any OpenDM running from source first, from its tray menu):

1. Run `dist\OpenDM-0.7.0-setup.exe`. No admin prompt appears. SmartScreen may warn (unsigned):
   More info -> Run anyway. On the folder page choose `D:\Apps\OpenDM` (any folder you like).
   Tick "Create a desktop shortcut". Finish with "Launch OpenDM".
2. The Start menu has OpenDM with the OpenDM icon. The taskbar button shows the OpenDM icon,
   and a finished-download notification says "OpenDM" (not "Python").
3. With the test server running, download `http://127.0.0.1:8765/file/a.bin?size=20M`.
4. Settings -> Browser shows Chrome and Edge "set up". In Chrome remove the unpacked extension
   loaded from the repo, then load the one from the install folder (`D:\Apps\OpenDM\extension`).
   Clicking a link on `http://127.0.0.1:8765/pages/links.html` reaches the installed OpenDM.
5. With OpenDM running, run the setup again: it asks you to close OpenDM first.
6. `D:\Apps\OpenDM\opendm-cli.exe list` lists the download.
7. Uninstall from Windows Settings -> Apps -> OpenDM. Answer **No** to deleting your data.
   `D:\Apps\OpenDM`, the shortcuts and the Start menu entry are gone;
   `reg query HKCU\Software\Google\Chrome\NativeMessagingHosts` shows no OpenDM entry;
   `%LOCALAPPDATA%\OpenDM` and your downloaded file are still there.
8. Portable: unzip `dist\OpenDM-0.7.0-portable.zip` to `D:\PortableTest`, run `OpenDM.exe`,
   go through the first-run wizard: a `data` folder appears next to it.
9. Optional, clean account: create a second Windows user, copy the setup there, install, use,
   uninstall (Windows 11 Home has no Windows Sandbox).
10. Restore the dev setup afterwards: `scripts\register_host_dev.cmd`, and reload the unpacked
    extension from `D:\Projects\opendm\extension` to keep testing from source.

## Release and update tests: M8

Automated (in `pytest`): versions and changelog (`tests/unit/test_versions.py`), updater
against a fake releases API on the test server (`tests/integration/test_updater.py`: newer
release found, drafts and unwanted pre-releases ignored, wrong or missing checksum refused,
links outside the project refused), tools folder rules and moving
(`tests/unit/test_tools_location.py`, `tests/gui/test_tools_location_gui.py`), media jobs
waiting for missing tools (`tests/integration/test_manager_media.py`), update dialog,
Settings -> Updates and wizard (`tests/gui/test_updates_gui.py`).

The release workflow runs on GitHub when a tag is pushed (`git push origin v0.8.0-rc.1`). It
creates a **draft** release; nothing is public until you press Publish.

Manual checklist:

> **Start setups and OpenDM from File Explorer or the Start menu, not from the Claude app's
> Terminal panel.** That panel keeps a private copy of the registry: a setup started there
> reports success, but its uninstall entry and browser keys never reach Windows, and an
> OpenDM started from there passes the same isolation on to the installer it launches.

1. On GitHub -> Actions, the "Release" run for `v0.8.0-rc.1` is green. Releases shows a
   draft "OpenDM 0.8.0-rc.1" with `OpenDM-0.8.0-rc.1-setup.exe`, the portable ZIP and
   `SHA256SUMS.txt`, and the notes from CHANGELOG.md. Edit it, tick "Set as a pre-release"
   (already ticked), and press **Publish release**.
2. Download the setup from that release page and install over your current OpenDM (same
   folder, e.g. `D:\Softtt\OpenDM`). Your downloads list and settings are still there.
3. Tools: a tray message says yt-dlp and FFmpeg moved; they are now in
   `D:\Softtt\OpenDM\tools`, no longer in Downloads. Settings -> Tools shows that folder and
   both tools as installed. Try to set the tools folder to your Downloads folder: OpenDM
   refuses with a message.
4. Missing tools: quit OpenDM, rename `D:\Softtt\OpenDM\tools` to `tools-x`, start OpenDM and
   add a YouTube link as MP3. The job waits ("waiting for yt-dlp and FFmpeg") and OpenDM asks
   once to download the tools. Cancel, rename the folder back, restart OpenDM: the job runs.
5. Playlist links: a YouTube link copied while a Mix plays (`...&list=RD...`) shows just that
   video, with "Show the whole playlist..." above the options.
6. Settings -> Updates: "You have OpenDM 0.8.0-rc.1". Tick "Check for a new OpenDM when it
   starts" and "Include test versions". Click **Check now**: "You have the latest version".
7. Tell Claude when you are here: it pushes `v0.8.0-rc.2`. Publish that draft as in step 1.
   Restart OpenDM: the update dialog shows 0.8.0-rc.2 and its notes. Click **Install**: it
   downloads, OpenDM closes, the installer opens; finish it. Settings -> Updates now says
   0.8.0-rc.2, and `D:\Softtt\OpenDM\updates` is empty after the next start.
8. "Skip this version" on an offered update keeps the startup check quiet about it; "Check
   now" still shows it. With the update check off, OpenDM makes no request to GitHub.
9. Portable: unzip the rc.1 portable ZIP into a new folder, turn on the update check there:
   the dialog offers "Open release page" instead of Install.
