# Privacy

OpenDM has no telemetry, no analytics, no ads and no account. Nothing is sent to the OpenDM
project. This page lists every place where data moves.

## Desktop app

- Downloads go directly from your computer to the server of the link you add.
- The tool manager contacts github.com (yt-dlp) and gyan.dev (FFmpeg) only when you click
  Download/Update or Check now, or weekly if you turned on the update check.
- Settings, history and queues stay in `%LOCALAPPDATA%\OpenDM`. Saved passwords and cookies are
  encrypted with Windows DPAPI (only your Windows account can read them).

## Browser extension (OpenDM Integration, Chrome and Edge)

The extension talks only to the OpenDM app on the same computer, through the browser's Native
Messaging (a local program, `io.github.indrajit147.opendm`). It makes no network requests of its
own and has no remote code.

### What it sends to the app, and when

| When | What is sent to OpenDM |
|---|---|
| A download starts and takeover applies (file type in the list, at least the minimum size, Alt not held) | link, final link, referrer, file name, size, browser user agent, and the cookies the browser holds **for that link's site** |
| You choose "Download with OpenDM" on a link, video or audio | the same, for that link |
| You choose "Download video on this page" (menu, popup, or the video button) | page address and title, user agent, cookies for that page's site |
| You choose "Download all links with OpenDM" | the page's http/https links, page address and title. **No cookies.** |
| You open the popup or press "Test connection" | a status request, no page data |

Cookies are needed for downloads behind a login. The app keeps them only with the download
(encrypted) and sends them only to that site. For video sites they reach yt-dlp through a
temporary file that is deleted when the job ends.

### Permissions

| Permission | Why |
|---|---|
| `downloads` | see new browser downloads, pause them, and cancel them once OpenDM has taken them over |
| `nativeMessaging` | talk to the OpenDM app |
| `contextMenus` | the "Download with OpenDM" menu items |
| `cookies` | read the cookies of the site being downloaded, so downloads behind a login work |
| `storage` | your extension settings (synced by the browser if you use sync) and the media list for open tabs (in memory only) |
| `webRequest` | see response **headers** (content type and length) to spot video, audio and stream manifests on a page. Bodies are never read; requests are never changed or blocked |
| `notifications` | tell you when OpenDM could not take a download (can be turned off) |
| host access to all sites | needed by `cookies`, `webRequest` and the content script on every site you visit |

### What stays in the browser

- The list of detected media for each tab is kept in session storage (memory) and cleared
  when the tab navigates or closes. It is sent to the app only when you click Download.
- The content script on each page only: notices Alt+click on links, lists links when you ask
  for "Download all links", and shows the video button. It does not read page text or forms.
