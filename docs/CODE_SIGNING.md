# Code signing

OpenDM's programs and installer are not signed today. Windows SmartScreen therefore shows
"Windows protected your PC" for new downloads until a file has built up reputation. Users
can check a download against the release's `SHA256SUMS.txt` (see [INSTALL.md](INSTALL.md)).

## Options

| Option | Cost | Notes |
|---|---|---|
| **SignPath Foundation** (free certificate for open-source projects, signing through SignPath.io in the GitHub release workflow) | Free | Has conditions, checked 2026-10-31 on [signpath.org/terms](https://signpath.org/terms), see below. Signing requests are approved by hand per release. The certificate is in SignPath Foundation's name, not the project's. |
| Buying an OV or EV code-signing certificate from a certificate authority | Paid, usually yearly | Since 2023 the private key must live on a hardware token or a cloud HSM, which makes signing on GitHub Actions harder. EV certificates no longer skip SmartScreen automatically. |
| A cloud signing service from Microsoft or another provider | Paid, monthly | Eligibility (individuals, countries) and identity checks vary; check the provider's current rules. |
| Stay unsigned | Free | Works, but every new release starts with the SmartScreen warning. |

**Recommendation:** apply to SignPath Foundation after 1.0 is released (one condition is
that the software is already released in the form to be signed).

## SignPath Foundation conditions and where OpenDM stands

| Condition | OpenDM |
|---|---|
| OSI-approved licence, no proprietary components | GPL-3.0-or-later; Qt (LGPL), Python, PyInstaller bootloader (GPL with exception). yt-dlp and FFmpeg are not shipped. |
| Actively maintained, already released, functionality documented on the download page | Yes after 1.0 (README, Releases page, user guide). |
| Only your own binaries, built from your own source; builds verifiable from source | Built by the public release workflow from tagged source. |
| No security tools that find/exploit vulnerabilities or bypass security | None. DRM is never bypassed. |
| Disclose data transfers in a privacy policy, **show it during installation**, offer a way to turn them off | [PRIVACY.md](PRIVACY.md); the installer shows a privacy note (`installer/privacy-note.txt`) before the folder page; the update check is off by default. |
| Announce system configuration changes; provide an uninstaller | The installer lists the browser registration; uninstaller included. |
| Team roles (authors, reviewers, approvers) and MFA for everyone on SignPath and GitHub | **To do:** turn on GitHub two-factor authentication and name the roles. |
| A "Code signing policy" section on the home and download pages (signing credit, team roles, privacy policy link) | **To do** once accepted (README and the release notes template). |
| Product name and version set consistently in each build | Already: version info from `opendm.__version__` in every program and the installer. |

## What changes in the release workflow once approved

After the build step, the workflow uploads `dist\OpenDM\*.exe` and the setup to SignPath,
waits for the manual approval, and continues with the signed files (smoke test, install
test, checksums, draft release). The `SHA256SUMS.txt` then covers the signed files.
