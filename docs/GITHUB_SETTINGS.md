# GitHub settings for OpenDM (maintainer checklist)

These need the repository owner's own login, so they are done by hand. GitHub moves its menus
from time to time; the names below are as of October 2026.

## 1. Two-factor authentication (account) - needed for code signing

1. Click your avatar (top right) -> **Settings** -> **Password and authentication**.
2. **Enable two-factor authentication**. An authenticator app (Microsoft Authenticator,
   Google Authenticator, ...) is the simplest; a passkey or security key also works.
3. **Download and keep the recovery codes** somewhere safe and offline. Without them a lost
   phone means a lost account.

## 2. Security features (repository)

Open https://github.com/Indrajit147/OpenDM -> **Settings** -> **Advanced Security** (on some
accounts called **Code security**), then turn on:

- **Private vulnerability reporting**: people can report security problems privately;
  [SECURITY.md](SECURITY.md) and the issue form already point there.
- **Dependabot alerts** and **Dependabot security updates**: warnings, and fix pull requests,
  when a dependency has a known vulnerability.
- **Secret scanning** and **Push protection** (free for public repositories): blocks pushes
  that contain tokens or passwords by mistake.

## 3. Protect the main branch

**Settings** -> **Rules** -> **Rulesets** -> **New ruleset** -> **New branch ruleset**:

- Name: `main`; Enforcement status: **Active**; Target branches: **Include default branch**.
- Tick **Restrict deletions** and **Block force pushes**. Save.

Leave "Require a pull request" and "Require status checks to pass" off for now: they block
direct pushes, which is how changes reach `main` in this project. CI still runs on every
push and the release workflow runs all tests before building.

## 4. Make the project easy to find

On the repository's main page, the gear next to **About**:

- Description: *Free, open-source download manager for Windows: multi-connection downloads,
  queues, video downloads, Chrome/Edge extension. No ads, no telemetry.*
- Website: `https://github.com/Indrajit147/OpenDM/releases/latest`
- Topics: `download-manager`, `windows`, `python`, `pyside6`, `yt-dlp`, `browser-extension`,
  `open-source`, `gpl-3`
- Tick **Releases**; untick **Packages** and **Deployments** if they are empty.

## 5. Actions (check only)

**Settings** -> **Actions** -> **General** -> *Workflow permissions*: **Read repository
contents and packages permissions** is enough; the release workflow asks for write access to
create its draft release by itself.

## 6. Later, for code signing

Once SignPath accepts OpenDM: **Settings** -> **Secrets and variables** -> **Actions**, as
listed in [CODE_SIGNING.md](CODE_SIGNING.md) step 4.
