# Code signing

OpenDM's programs and installer are not signed today. Windows SmartScreen therefore shows
"Windows protected your PC" for new downloads until a file has built up reputation. Users
can check a download against the release's `SHA256SUMS.txt` (see [INSTALL.md](INSTALL.md)).

**Status (2026-10-31):** SignPath Foundation declined the first application (not enough
public visibility yet) and invited a new one later; see D71. Reapply with the answers below
once OpenDM has stars, store users or outside mentions to list under *Reputation*.

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
| Team roles (authors, reviewers, approvers) and MFA for everyone on SignPath and GitHub | GitHub two-factor authentication on (2026-10-31); roles named in the README. |
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
2. Apply on [signpath.org/apply](https://signpath.org/apply). The form's fields (as of
   2026-10-31) and answers you can paste:
   - **Project Name:** OpenDM
   - **Repository URL:** https://github.com/Indrajit147/OpenDM
   - **Homepage URL:** https://github.com/Indrajit147/OpenDM
   - **Download URL** (the page must mention SignPath Foundation; the README's code signing
     policy does): https://github.com/Indrajit147/OpenDM#code-signing-policy
   - **Privacy Policy URL:** https://github.com/Indrajit147/OpenDM/blob/main/docs/PRIVACY.md
   - **Wikipedia URL:** leave empty.
   - **Tagline:** Free, open-source download manager for Windows with no ads and no
     telemetry.
   - **Category:** the closest to "Utilities" / "Networking" in the list.
   - **Description:** OpenDM is a free, open-source (GPL-3.0-or-later) download manager for
     Windows. It speeds up and organises downloads with multi-connection transfers, pause
     and resume, queues and schedules, downloads videos and audio through yt-dlp with the
     user's consent, and takes over browser downloads through a Chrome/Edge extension. It
     has no ads, no account and no telemetry, and refuses DRM-protected content. Releases are
     built by a public GitHub Actions workflow from tagged source.
   - **Reputation:** state it honestly; the project is new. For example: "New project, first
     stable release 1.0.0 on 2026-10-31. Fully public development history, CI and release
     workflow on GitHub; an Edge Add-ons listing is in review." Add store links, stars or
     articles as they come.
   - **Maintainer Type:** individual.
   - **Build System:** GitHub Actions.
   - **First/Last Name, Email:** your own (this creates your SignPath account).
   - Tick the Code of Conduct box (certificates are issued in SignPath Foundation's name) and
     the personal-data box; the marketing box is optional.
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
