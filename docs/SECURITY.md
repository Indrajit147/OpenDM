# Security

## Reporting a problem

Please report security problems privately, not in a public issue: on GitHub open
**Security -> Report a vulnerability** on the
[OpenDM repository](https://github.com/Indrajit147/OpenDM/security). Include the OpenDM
version (Settings -> Updates) and, if it helps, an "Export diagnostics" ZIP (Settings ->
General; links, cookies and passwords are removed from it). You will get an answer within a
week. Fixes are released as a new version with a note in [CHANGELOG.md](../CHANGELOG.md).

Supported: the latest release only.

## Review against the specification (M9, 2026-10-31)

Each rule from section 7 of [PROJECT_SPEC.md](PROJECT_SPEC.md), what OpenDM does and the test
that keeps it true.

| Rule | How OpenDM meets it | Checked by |
| --- | --- | --- |
| Never `shell=True`; arguments as lists | No shell anywhere. Programs start in four places only: yt-dlp/FFmpeg (in a Windows job object that ends them with OpenDM), the browser host starting OpenDM, "shut down after the queue" (after a countdown you can cancel) and the update installer. | `tests/unit/test_security_rules.py` scans the source |
| Clean file names | Reserved names (CON, NUL, COM1...), illegal characters, trailing dots/spaces, `..` and path separators, and over-long names are fixed before a file is created. | `tests/unit/test_filenames.py` |
| Never run downloaded files | OpenDM opens a finished file only when you click Open, and asks again for programs and scripts (.exe, .msi, .bat, ...). The one program it runs on its own is the update installer, and only after you clicked Install and its SHA-256 matched the release's `SHA256SUMS.txt`. | `test_security_rules.py`, `tests/integration/test_updater.py` |
| The pipe only for the current user | The app's pipe (used by `opendm-cli` and the browser host) is created with "current user only" permissions; the name contains the user name. | `tests/gui/test_ipc.py::test_pipe_is_open_only_to_this_user` reads its Windows permissions |
| Validate every pipe and browser message | Fixed command list, typed and length-limited fields, 1 MB per pipe message, 4 MB per browser message; anything else is refused. Only `http(s)` links are accepted from the browser. | `tests/unit/test_ipc_protocol.py`, `tests/unit/test_native_host.py` |
| TLS on by default | Certificate checks are on for every download. They can be turned off only for one download, after a certificate error, with a warning (or `opendm-cli get --insecure`). | `test_security_rules.py`, `tests/gui/test_tls_override.py` |
| No telemetry | Network traffic is your downloads, the tool downloads you agree to, and the update check if you turn it on. | [PRIVACY.md](PRIVACY.md) |

Also:

- **Cookies and login headers** from the browser are stored encrypted with Windows DPAPI (only
  your Windows account can read them) and are never written to logs. For yt-dlp they go into
  a temporary cookie file that is deleted right after use.
- **Tools and updates** come only from fixed official addresses (yt-dlp's GitHub releases,
  gyan.dev for FFmpeg, this repository's releases) and must match their published SHA-256
  before they are used. A tool update that does not run is rolled back.
- **Logs** remove link query strings, user names and passwords in links, cookies and
  authorization values before anything is written.
- **DRM**: protected streams are detected and refused (spec section 2).

## Known limits

- The programs are not code-signed yet, so Windows SmartScreen warns on first run. See
  [CODE_SIGNING.md](CODE_SIGNING.md).
- The browser extension can see the pages you visit (it needs that to find downloads and
  videos). It sends a link to OpenDM only when you start a download; see
  [PRIVACY.md](PRIVACY.md).
- OpenDM trusts the tools it installed. If someone can already write to its `tools` folder,
  they could replace them; the folder is inside your own install folder.
