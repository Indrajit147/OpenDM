# Installing OpenDM

OpenDM runs on Windows 10 (1809 or later) and Windows 11, 64-bit. It needs no admin rights.

## Installer (recommended)

1. Open the [Releases page](https://github.com/Indrajit147/OpenDM/releases) and download
   `OpenDM-<version>-setup.exe` from the newest release.
2. Optional: check the download. In Command Prompt:
   `certutil -hashfile OpenDM-<version>-setup.exe SHA256` and compare the result with the line
   for that file in the release's `SHA256SUMS.txt`.
3. Double-click the setup **in File Explorer**. The builds are not code-signed yet, so Windows
   SmartScreen may say "Windows protected your PC": choose **More info -> Run anyway** (only
   for a file you downloaded from this repository's Releases page).
4. Choose a folder. The default is `%LOCALAPPDATA%\Programs\OpenDM`; any folder on another
   drive (for example `D:\Apps\OpenDM`) works too. Tick "Create a desktop shortcut" if you
   want one.
5. Finish with "Launch OpenDM". The first-run wizard asks where downloads should go and
   whether OpenDM may check for updates (both can be changed later in Settings).

OpenDM is installed for your Windows account only. Video tools (yt-dlp and FFmpeg) are not
included; OpenDM offers to download them the first time you download a video, into the
`tools` folder inside the install folder.

## Portable version

Download `OpenDM-<version>-portable.zip`, unzip it anywhere (a USB drive works) and run
`OpenDM.exe`. Settings, history and video tools stay in the `data` folder next to it, and
nothing is written to the registry except when you set up the browser connection.

## Browser extension (Chrome and Edge)

1. In OpenDM open **Settings -> Browser** and click **Set up for Chrome and Edge**.
2. In Chrome open `chrome://extensions` (Edge: `edge://extensions`), turn on
   **Developer mode**, click **Load unpacked** and choose the `extension` folder shown in
   Settings -> Browser (for example `D:\Apps\OpenDM\extension`).
3. Click the OpenDM icon in the browser toolbar: it should say "Connected".

Store versions for the Chrome Web Store and Edge Add-ons are being prepared; once they are
published you can install from there instead.

## Updating

- With **Settings -> Updates -> Check for a new OpenDM when it starts** turned on, OpenDM
  shows new versions with their release notes. **Install** downloads the installer, checks it
  against the release's SHA-256 and runs it after OpenDM closes. Your settings, history and
  tools are kept.
- Or install the new setup over the old one by hand (same folder).
- Portable: download the new ZIP and unzip it over the old folder; the `data` folder stays.

## Uninstalling

Windows **Settings -> Apps -> Installed apps -> OpenDM -> Uninstall**. It removes the
programs, the video tools and the browser connection, and asks whether to delete your
settings and download history as well. Files you downloaded are never deleted. Remove the
browser extension from `chrome://extensions` yourself.
