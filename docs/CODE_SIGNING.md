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
| A "Code signing policy" section on the home and download pages (signing credit, team roles, privacy policy link) | The README has the section with roles and the privacy policy; the credit line is added once SignPath accepts the project. |
| Product name and version set consistently in each build | Already: version info from `opendm.__version__` in every program and the installer. |

## The release workflow is ready (D69)

`.github/workflows/release.yml` already contains the signing steps; they are skipped while
the repository variable `SIGNPATH_ORGANIZATION_ID` is empty, so releases stay unsigned
until SignPath is set up. With it set, a release:

1. builds the three programs (`scripts\build.py --stage programs`);
2. sends `OpenDM.exe`, `opendm-cli.exe` and `opendm-host.exe` to SignPath (artifact
   configuration `programs`) and waits until you approve the request in SignPath;
3. builds the portable ZIP and the installer from the signed programs (`--stage package`);
4. sends the setup to SignPath (artifact configuration `installer`) and waits again;
5. runs the smoke and install tests on the signed files and writes `SHA256SUMS.txt` for them.

## Applying: step by step (maintainer)

1. Turn on two-factor authentication on GitHub (see [GITHUB_SETTINGS.md](GITHUB_SETTINGS.md)).
2. Apply on [signpath.org](https://signpath.org) ("Apply for free code signing"). Answers
   you can paste:
   - **Project:** OpenDM, https://github.com/Indrajit147/OpenDM, GPL-3.0-or-later.
   - **Description:** A free, open-source download manager for Windows (multi-connection
     downloads, queues, video downloads through yt-dlp, a Chrome/Edge extension). No
     telemetry; DRM-protected content is refused.
   - **What is signed:** `OpenDM.exe`, `opendm-cli.exe`, `opendm-host.exe` (PyInstaller) and
     the Inno Setup installer `OpenDM-<version>-setup.exe`, built by the public GitHub
     Actions release workflow on GitHub-hosted runners from tagged source.
   - **Third-party components:** Python, Qt for Python (LGPL-3.0), httpx, PyInstaller
     bootloader (GPL with exception). yt-dlp and FFmpeg are not shipped; the app downloads
     them with the user's consent.
   - **Releases:** https://github.com/Indrajit147/OpenDM/releases (1.0.0, 2026-10-31).
   - **Privacy policy:** https://github.com/Indrajit147/OpenDM/blob/main/docs/PRIVACY.md
   - **Team:** Indrajit Gupta (author, reviewer, approver).
3. When SignPath accepts the project, in SignPath:
   - add the predefined **GitHub.com trusted build system** to the organization and link
     it to the project;
   - create two **artifact configurations** with these slugs:
     - `programs`:
       ```xml
       <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
         <zip-file>
           <pe-file path="OpenDM.exe" />
           <pe-file path="opendm-cli.exe" />
           <pe-file path="opendm-host.exe" />
         </zip-file>
       </artifact-configuration>
       ```
     - `installer`:
       ```xml
       <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
         <zip-file>
           <pe-file path="OpenDM-*-setup.exe" />
         </zip-file>
       </artifact-configuration>
       ```
   - note the organization ID, project slug and signing policy slug, and create an API
     token for a CI user that may submit requests.
4. In GitHub, repository **Settings -> Secrets and variables -> Actions**:
   - secret `SIGNPATH_API_TOKEN` = the API token;
   - variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`.
5. Tell Claude: the next release (for example 1.0.1) is the first signed one; the README's
   code signing policy then gets SignPath's required credit line.
