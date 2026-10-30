# Architecture decisions

One entry per decision: context, options, pros/cons, choice. D1–D15 come from the
specification (section 4); later entries were made during development.

## D1 Language and GUI
- **Context:** Need a polished native-looking Windows GUI, built quickly by a Python-literate owner.
- **Options:** Python 3.12 + PySide6; C#/.NET WPF; Rust/Tauri; Electron.
- **Pros/cons:** Python is the fastest route to a working product and PySide6 gives a high-DPI
  Qt UI; cons are a larger installer (~80–120 MB) and slower raw performance, which matters
  little because downloading is network-bound.
- **Choice:** Python 3.12 + PySide6.

## D2 Concurrency
- **Options:** engine asyncio loop on a background thread + Qt signals; qasync single loop;
  thread per connection.
- **Pros/cons:** background loop keeps the GUI responsive and the engine GUI-free and testable,
  avoids qasync edge cases; cost is a command/event bridge (`core/bridge.py`).
- **Choice:** background asyncio thread + bridge.

## D3 HTTP client
- **Options:** httpx (async); aiohttp; urllib.
- **Pros/cons:** httpx has a clean API, HTTP/1.1 + optional HTTP/2, good timeouts and proxies;
  aiohttp is slightly faster but rougher.
- **Choice:** httpx behind a `Transport` interface so it can be swapped.

## D4 Media sites and HLS/DASH
- **Options:** delegate to yt-dlp; own HLS/DASH parser and extractors.
- **Pros/cons:** yt-dlp covers thousands of sites and is maintained; writing our own would be
  huge and stale. Cost: external dependency that breaks when sites change (mitigated by D5).
- **Choice:** yt-dlp for media; own engine for direct files.

## D5 yt-dlp integration
- **Options:** official `yt-dlp.exe` subprocess; import as a library.
- **Pros/cons:** subprocess updates independently of the app and isolates crashes; progress must
  be parsed (use `--newline` and a JSON `--progress-template`).
- **Choice:** subprocess.

## D6 FFmpeg
- **Options:** downloaded on first use by the Tool Manager; bundled in the installer.
- **Pros/cons:** download-on-demand keeps the installer small and avoids GPL redistribution
  complexity; costs a one-time consent dialog and download.
- **Choice:** Tool Manager download into a user-chosen folder.

## D7 Persistence
- **Options:** SQLite (stdlib, WAL); JSON files.
- **Choice:** SQLite with a small migration system: atomic, queryable, safe concurrent access.

## D8 On-disk download format
- **Options:** one preallocated `name.ext.odm-part` with positioned writes + state sidecar;
  one temp file per segment then merge.
- **Pros/cons:** single file needs no merge step and no doubled disk usage (important on a
  full disk). Renamed to the final name on completion.
- **Choice:** single preallocated file + sidecar.

## D9 Browser to app channel
- **Options:** MV3 extension + Native Messaging host; localhost HTTP server.
- **Pros/cons:** Native Messaging is officially supported and reachable only by our extension;
  a localhost server risks port conflicts and calls from arbitrary websites.
- **Choice:** Native Messaging.

## D10 Host to running app IPC
- **Options:** `QLocalServer`/`QLocalSocket` (named pipe); TCP localhost.
- **Choice:** named pipe: user-scoped, no port, doubles as the single-instance lock.

## D11 Packaging
- **Options:** PyInstaller onedir; PyInstaller onefile; Nuitka.
- **Choice:** onedir: fast startup, fewer antivirus false positives. Revisit Nuitka after v1.

## D12 Installer
- **Options:** Inno Setup per-user; WiX/MSI; MSIX.
- **Choice:** Inno Setup: free, scriptable, directory-choice page, writes HKCU keys for
  Native Messaging, no admin rights. MSIX needs signing and has restrictions.

## D13 Updates and telemetry
- **Choice:** opt-in update check against GitHub Releases; no telemetry.

## D14 Research approach
- **Options:** clean-room from public specs + local test server; reverse engineering.
- **Choice:** clean-room. Reverse engineering is a legal risk, slow and unnecessary.

## D15 Browsers
- **Options:** Chrome + Edge first (same MV3 code); Firefox.
- **Choice:** Chrome + Edge for v1; Firefox post-1.0.

## D16 Python distribution for development (M0, 2026-10-30)
- **Context:** The only Python 3.12 on the dev machine was the Microsoft Store build on C:.
  Store Python virtualizes writes under `%LOCALAPPDATA%`, which would hide the app data dir
  and Native Messaging files from other processes during development.
- **Options:** python.org 3.12 installed per-user on D:; the existing Python 3.14 on D:;
  the Store 3.12.
- **Pros/cons:** python.org 3.12 matches the spec and CI exactly with no virtualization;
  3.14 is ahead of PySide6/PyInstaller support; the Store build has the redirect problem.
- **Choice:** python.org 3.12.10 x64 at `D:\Tools\Python312` (installer MD5 and Authenticode
  signature verified), not on PATH.

## D17 Test server implementation (M0, 2026-10-30)
- **Context:** Need a local HTTP server with byte-exact fault injection (drop at byte N,
  throttling, validator changes, 200 instead of 206...).
- **Options:** stdlib `http.server` (ThreadingHTTPServer); aiohttp/Starlette + uvicorn.
- **Pros/cons:** stdlib needs no dependency and gives full control of the socket (exact byte
  counts, FIN mid-body); frameworks add dependencies and hide transport details.
- **Choice:** stdlib. Faults are combinable query parameters on `/file/<name>`; content is
  generated deterministically from `(size, seed)` (100 MiB in ~0.3 s), so no fixture files.
  Mid-body drops use FIN rather than RST so the client receives exactly N bytes.

## D18 Build backend (M0, 2026-10-30)
- **Options:** setuptools; hatchling; flit.
- **Choice:** setuptools (MIT, ubiquitous, supports PEP 639 `license = "GPL-3.0-or-later"`
  from 77+). Packaging to .exe is PyInstaller's job (D11), so the backend only matters for dev installs.

## D19 License replacement (M0, 2026-10-30)
- **Context:** The GitHub repo was created with an MIT LICENSE; the spec requires
  GPL-3.0-or-later. The repo owner is the sole author, so relicensing is unrestricted.
- **Choice:** replaced with the GPL-3.0 text from gnu.org, per the spec. Confirmed by the owner.

## D20 Pause semantics in M1 (2026-10-30, approved)
- **Context:** M1 has pause but no state sidecar (M2).
- **Choice:** pause keeps `.odm-part` and the in-memory SHA-256 state; resume sends
  `Range` + `If-Range` (strong ETag, else Last-Modified). A 200 reply (no ranges, or validator
  changed) restarts from zero. An outside task cancellation (app exit) counts as a pause.

## D21 CLI Ctrl+C (2026-10-30, approved; superseded by D29 in M2)
- **Choice:** Ctrl+C cancels and deletes the partial file (exit code 130); it cannot be resumed
  until M2 adds the sidecar. Failed downloads keep `.odm-part` and report its path.

## D22 Existing files (2026-10-30, approved)
- **Choice:** never overwrite; pick `name (1).ext`, `name (2).ext`... A name whose `.odm-part`
  exists counts as taken, and the name is reserved by creating the empty partial file.

## D23 User agent and encoding (2026-10-30, approved)
- **Choice:** default `User-Agent: OpenDM/<version>`, overridable (the extension passes the
  browser's UA in M6). Send `Accept-Encoding: identity`; if a server compresses anyway, httpx
  decodes it and the size is treated as unknown.

## D24 Filename detection (2026-10-30, approved)
- **Choice:** `filename*` (RFC 5987, UTF-8/ISO-8859-1) > `filename` > last segment of the final
  URL after redirects > `download`; add an extension from Content-Type when missing, and replace
  script extensions (.php, .aspx...) taken from the URL. Lenient fixes: raw UTF-8 bytes decoded
  as Latin-1 are repaired; `%XX` in plain `filename` is decoded only when it forms valid UTF-8.

## D25 Error kinds (2026-10-30)
- **Choice:** `ErrorKind` with a `retryable` property (CONNECTION, NETWORK, TIMEOUT, SERVER).
  403 maps to LINK_EXPIRED (the "Refresh link" flow in M2); 404/410 to NOT_FOUND; 408/429/5xx
  to SERVER. CONNECTION (could not connect at all) is separate from NETWORK so the probe does
  not retry HEAD as GET against an unreachable host (each refused attempt costs ~2 s on Windows).

## D26 Filename safety limits (2026-10-30)
- **Choice:** components are limited to 255 UTF-16 units; full paths to 259 characters
  (including `.odm-part`) unless Windows long paths are enabled (registry `LongPathsEnabled`).
  Reserved device names get an underscore (`CON.txt` -> `CON_.txt`), including `COM¹`-style names.

## D27 Crash-safe checkpoints (M2, 2026-10-30)
- **Context:** the spec requires surviving app kill and reboot without corrupting data.
- **Options:** state written with every chunk; periodic state without fsync; periodic
  fsync-then-state.
- **Choice:** every 2 s and on pause/exit/failure: snapshot per-segment `written` on the event
  loop, fsync the `.odm-part`, then save `.odm-state` atomically (temp file, fsync, rename).
  The state can only under-claim, so a kill costs at most ~2 s of re-download. Segments track
  `received` (incl. buffered) separately from `written` (handed to the OS); splits use `received`.

## D28 State file contents (M2, 2026-10-30, approved)
- **Choice:** version, SHA-256 of the request URL, size, ETag, Last-Modified, accepts-ranges and
  `[start, end, written]` per segment. No URL, cookies or headers (URLs often carry tokens).
  A damaged or unknown-version file is ignored and the download starts over.

## D29 Ctrl+C and re-running (M2, 2026-10-30, approved; replaces D21)
- **Choice:** Ctrl+C pauses (checkpoint kept, exit 130). Running the same `get` with the same
  URL and folder resumes in place (matched by URL hash and validators); `--restart` discards it;
  `--continue FILE.odm-part` continues from a different (refreshed) URL.

## D30 Checksum mismatch (M2, 2026-10-30, approved)
- **Choice:** the file is renamed to its final name, the job is FAILED with CHECKSUM_MISMATCH and
  exit code 1. Rejected alternative: leaving it as `.odm-part` (users think it vanished).

## D31 Hash after download (M2, 2026-10-30, approved)
- **Choice:** SHA-256 (and any user checksum) is computed by reading the finished file in a worker
  thread (VERIFYING state). One code path for multi-segment and resumed downloads, and it proves
  the bytes on disk, not the bytes we believe we wrote. Cost: ~1-2 s per GB.

## D32 Fallbacks and validator changes (M2, 2026-10-30)
- **Choice:** every ranged GET carries `If-Range`. A `200` reply is compared with the probe's
  validators: changed -> VALIDATOR_CHANGED (progress kept until the user restarts); unchanged ->
  the server ignores ranges -> one connection from the start (state file removed). A single
  segment starting at 0 accepts a 200 as the whole body.

## D33 Retries and connection limits (M2, 2026-10-30, approved)
- **Choice:** per segment, 5 retries with full-jitter backoff 1 s -> 30 s; a server Retry-After
  wins (capped at 60 s); the counter resets when a retry made progress. A 429/503 while other
  connections are active is read as "too many connections": that segment is re-queued and the
  download's connection count drops to the number still active. Cross-download per-host limits: M3.

## D34 Speed limiting and writes (M2, 2026-10-30)
- **Choice:** token bucket that starts empty, allows 0.1 s of burst and lets the balance go
  negative (callers sleep off the debt). Each download has one; a global bucket can be shared.
  Data is buffered up to 1 MiB per connection and written with positioned writes from a worker
  thread (Windows has no `os.pwrite`, so seek+write is serialized by a lock).

## D35 Database access (M3, 2026-10-30)
- **Choice:** one SQLite connection in autocommit mode, owned by the engine loop's thread.
  Writes are small (progress at most every 2 s per job), so they run inline. WAL mode,
  `synchronous=NORMAL`, foreign keys on. Migrations are numbered `.sql` files, each applied
  with its `user_version` bump in one transaction; a newer database than the app is refused.

## D36 Secrets at rest (M3, 2026-10-30, approved)
- **Choice:** cookies and `Cookie`/`Authorization`/`Proxy-Authorization` headers are encrypted
  with Windows DPAPI (current user, extra entropy) via `ctypes`; other headers are plain JSON.
  Without DPAPI they are not stored. A blob that cannot be decrypted (other user/PC) is ignored.

## D37 Restart behaviour (M3, 2026-10-30, approved)
- **Choice:** on start, jobs left in probing/downloading/verifying become PAUSED "interrupted";
  on a clean exit running jobs are paused the same way. Nothing starts by itself except a queue
  whose schedule window is open.

## D38 Queue semantics (M3, 2026-10-30)
- **Choice:** a queue only starts its QUEUED jobs while active (started by the user or its
  schedule), up to `max_concurrent`, in position order. "Start now" bypasses the queue. Stopping
  a queue (by hand or at its stop time) puts its jobs back to QUEUED, unlike a user pause
  (PAUSED). Schedules act on window edges, so a queue stopped by hand is not restarted until
  its next window.

## D39 After-queue actions (M3, 2026-10-30, approved)
- **Choice:** `QueueFinished` is emitted only when an active queue runs out of work after
  running at least one job, never when stopped and never for an empty queue. Sleep/shutdown go
  through a `PowerActions` interface; M3 ships a no-op, M4 adds the 60 s cancellable countdown.

## D40 Per-host limits (M3, 2026-10-30, approved)
- **Choice:** 8 connections per host shared by all downloads, granted when a job starts
  (`min(wanted, free)`); a job waits while its host has no free connection.

## D41 Categories (M3, 2026-10-30, approved)
- **Choice:** the longest matching extension wins (`tar.gz` before `gz`), ties go to the first
  category, otherwise the fallback ("Other"). Folders: empty = base folder, relative = inside
  it, absolute = as is. Defaults: `<Downloads>\Video`, `\Audio`, `\Documents`, `\Compressed`,
  `\Programs`; Other in `<Downloads>`. `<Downloads>` comes from the Known Folder API.

## D42 Qt package (M4, 2026-10-30, approved)
- **Choice:** `PySide6-Essentials` 6.12 only (~209 MB installed in `.venv`), not the full
  `PySide6` meta-package (+39 MB Addons). The speed graph and segment map are drawn with
  QPainter (original design), so Qt Charts is not needed.

## D43 GUI <-> engine (M4, 2026-10-30, approved)
- **Choice:** `core/bridge.py` runs loop + database + manager on one thread. The GUI calls
  `engine.call(fn)` (future, callbacks delivered on the GUI thread through a queued signal) and a
  250 ms timer drains events, keeping only the newest progress per job (~4 Hz, spec 6.4).
  Job changes travel as `JobSnapshot` copies, so the GUI never reads SQLite. The app reads its
  settings once at startup with a blocking call; everything else is asynchronous.

## D44 IPC and single instance (M4, 2026-10-30; corrects D10)
- **Finding:** on Windows several `QLocalServer`s can listen on one pipe name, so the pipe is
  not a single-instance lock (a test documents this).
- **Choice:** the lock is a per-user named mutex (`Local\opendm-ipc-<user>`, `CreateMutexW`;
  released by the OS if the process dies). The pipe server uses `UserAccessOption`. The client
  is plain file I/O on `\\.\pipe\...` so the CLI and (M6) the Native Messaging host need no Qt.
  Protocol: one JSON object per line, versioned, strict per-command argument schemas, http/https
  only, header-injection checks, 1 MiB limit. `OPENDM_IPC_NAME` overrides the pipe name so tests
  never touch a real running app.

## D45 Desktop behaviour (M4, 2026-10-30, approved)
- **Choice:** closing the window keeps OpenDM in the tray (a one-time notice; setting to turn it
  off); Quit is in the tray menu. Clipboard monitor is opt-in and only reacts to single links
  whose path ends in a known category extension. Completion notifications are on by default.
- Opening a downloaded program or script (`.exe .msi .bat .ps1 .js .lnk ...`) always asks first;
  nothing is ever opened automatically (spec 7).

## D46 After-queue power actions (M4, 2026-10-30, approved)
- **Choice:** the engine emits `PowerRequested`; the GUI shows a 60 s countdown with Cancel and
  "Do it now". Shutdown runs `shutdown /s /t 0` (argument list, no shell); sleep calls
  `powrprof.SetSuspendState(False, False, False)`. Tests inject a fake and never call either.

## D47 Proxy (M4, 2026-10-30, approved)
- **Choice:** Windows/system proxy (default), no proxy, or a manual HTTP(S) proxy URL, applied
  to downloads started afterwards. SOCKS needs the `socksio` package: deferred, to be asked
  about separately.

## D48 Visual checks (M4, 2026-10-30)
- **Choice:** `scripts/screenshots.py` renders the real windows with live test-server downloads
  into `build/screens` without showing anything on screen (`grab()` on hidden widgets). The
  offscreen Qt platform has no usable fonts on Windows, so screenshots use the native platform.

## D49 Tool sources and verification (M5, 2026-10-30, approved)
- **Choice:** yt-dlp from the official GitHub release (API `releases/latest`; every download URL
  must start with `github.com/yt-dlp/yt-dlp/releases/download/`), verified against the release's
  `SHA2-256SUMS`. FFmpeg "release essentials" from gyan.dev (smaller than BtbN's 186 MB GPL
  build, a numbered release), verified against its published `.sha256`; only `bin/ffmpeg.exe`,
  `bin/ffprobe.exe` and `LICENSE` are extracted, to fixed paths (no zip-slip). A new tool replaces
  the old one only after the checksum matches; the old one is kept as `*.old` and restored if the
  new one does not run. Consent dialog first, always. The checksum files come from the same
  source as the tool (integrity, not an independent signature; yt-dlp's GPG signature is not
  checked yet).

## D50 Child processes (M5, 2026-10-30)
- **Choice:** yt-dlp/FFmpeg run with argument lists, no console window, inside a Windows Job
  Object with KILL_ON_JOB_CLOSE: pausing stops the whole process tree, and if OpenDM dies the OS
  ends them. A test proves a grandchild process is killed on pause.

## D51 DRM detection (M5, 2026-10-30, approved: AES-128 allowed)
- **Finding:** yt-dlp did not flag a DASH manifest with Widevine `ContentProtection` and would have
  downloaded it.
- **Choice:** besides yt-dlp's own flags and errors, OpenDM reads every stream manifest yt-dlp
  reports (and direct `.m3u8`/`.mpd` links) itself: HLS `SAMPLE-AES*` or a FairPlay/Widevine/
  PlayReady `KEYFORMAT`, and any DASH `ContentProtection` (CENC or a DRM system) is refused with
  "protected content is not supported". Plain HLS AES-128 is allowed (not DRM).

## D52 Media jobs (M5, 2026-10-30, approved)
- **Choice:** a job kind (`http`/`media`, schema v2) with the quality options as JSON.
  `MediaDownload` has HttpDownload's interface; pause = stop the process tree, resume = rerun with
  `--continue`; yt-dlp keeps its partial files next to the target. Each selected playlist item is
  its own job. The SHA-256 of the result is computed like for HTTP downloads. Speed limits are
  passed as `--limit-rate` (the shared global limiter does not apply to yt-dlp).

## D53 Cookies for yt-dlp (M5, 2026-10-30)
- **Choice:** Netscape cookie file created exclusively (`O_EXCL`, mode 0600) in
  `%LOCALAPPDATA%\OpenDM\tmp`, passed with `--cookies`, deleted when the job ends; cookie values
  never appear on the command line, and Authorization headers are never passed to yt-dlp.

## D54 Media tests (M5, 2026-10-30)
- **Choice:** a fake yt-dlp (Python script) covers runner logic everywhere, including CI. Tests
  with the real tools (`@pytest.mark.tools`) run when `OPENDM_TEST_TOOLS` points at a folder with
  `yt-dlp\yt-dlp.exe` and `ffmpeg\bin\ffmpeg.exe`; fixtures (MP4, HLS, DASH with separate tracks,
  subtitles, SAMPLE-AES HLS, Widevine DASH) are generated by `scripts/make_media_fixtures.py` and
  git-ignored. CI skips them for now (it would download ~130 MB of tools per run).

## D55 Tools folder (M5, 2026-10-30)
- **Choice:** the app downloads tools into Settings -> Tools folder (the user chose a folder in the
  project: `D:\Projects\opendm\tools-bin`, git-ignored). "Use existing..." points at copies the
  user already has (stored as `ytdlp_path`/`ffmpeg_path`). The weekly update check is opt-in and
  only notifies; installing always needs a click.
