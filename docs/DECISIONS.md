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

## D21 CLI Ctrl+C (2026-10-30, approved)
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
