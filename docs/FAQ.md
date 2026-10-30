# FAQ

**Windows says "Windows protected your PC" when I run the setup.**
OpenDM's programs are not code-signed yet (signing costs money or needs an approved
open-source program; see [CODE_SIGNING.md](CODE_SIGNING.md)). If you downloaded the setup
from this repository's Releases page, choose *More info -> Run anyway*. You can check the
file against `SHA256SUMS.txt` first (see [INSTALL.md](INSTALL.md)).

**Is OpenDM really free? Does it collect data?**
Yes, free and open source (GPL-3.0-or-later), with no ads, no account and no telemetry.
It only connects to the internet for your downloads, for tools you agree to download, and
for the update check if you turn it on. Details: [PRIVACY.md](PRIVACY.md).

**Where do my files go?**
Into the download folder you chose (default: your Windows Downloads folder), sorted into
Video, Audio, Documents, Compressed and Programs subfolders. Unfinished downloads keep a
`.odm-part` file next to the final name until they complete.

**Where are OpenDM's own files?**
The programs and video tools are in the install folder (`tools` for yt-dlp and FFmpeg).
Settings, history and logs are in `%LOCALAPPDATA%\OpenDM` (portable: the `data` folder).

**A video download fails.**
Update yt-dlp first (*Settings -> Tools -> Download / update*): websites change often. If it
still fails, export diagnostics (*Settings -> General*) and open an issue.

**A YouTube video says it needs me to sign in.**
Videos that need a login (members-only, some age-restricted ones) do not work yet: yt-dlp
needs an extra JavaScript runtime for them. Public videos work.

**Can OpenDM download from Netflix, Disney+, Spotify...?**
No. DRM-protected content is not supported, and OpenDM does not bypass paywalls, logins or
CAPTCHAs.

**The browser does not send downloads to OpenDM.**
Check *Settings -> Browser* in OpenDM says "set up" (click *Repair* if not), that the
extension is loaded from OpenDM's `extension` folder, and that its options have *Send browser
downloads to OpenDM* on. The extension's *Test connection* button checks the link to the app.
Files smaller than the minimum size in its options stay in the browser.

**A download stopped with "link expired".**
Many sites give links that work only for a while. Right-click the download, *Refresh link...*,
and paste a new link from the website (or start the download from the browser again).

**Can I limit the speed or download at night?**
Yes: *Settings -> Connections* for a total speed limit, and **Queues** for start and stop
times, with sleep or shut down when the queue is done.

**How do I uninstall?**
Windows *Settings -> Apps -> OpenDM -> Uninstall*. Your downloaded files are never deleted;
you choose whether your settings and history go too.

**How do I report a bug or a security problem?**
Bugs: [open an issue](https://github.com/Indrajit147/OpenDM/issues/new/choose) and attach an
*Export diagnostics* ZIP. Security problems: privately, see [SECURITY.md](SECURITY.md).
