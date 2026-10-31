# OpenDM user guide

## Downloading a file

- **Add URL** (toolbar or tray menu): paste one link, or use the **Batch** tab for many links
  or a pattern such as `https://example.com/img[001-120].jpg`.
- **Drag and drop** links onto the window.
- **Copy a link**: with *Settings -> General -> Offer to download links I copy* on, OpenDM
  offers it in a notification.
- **From the browser**: see [Browser](#browser) below.

The start dialog shows the name, size and folder. You can rename the file, change the
category or folder, pick a queue, and paste a checksum (`sha256:...`, `sha1:...` or `md5:...`)
that OpenDM verifies at the end. **Start now** downloads immediately; **Add to queue** waits
for the queue.

OpenDM opens up to 8 connections per download by default (*Settings -> Connections*, up to
32) and resumes after a pause, a lost connection or a crash. If a website's link expires,
right-click the download, choose *Refresh link...* and paste a new one: OpenDM checks it is the
same file and continues.

## The main window

- The sidebar filters by **Categories** (Video, Audio, Documents, Compressed, Programs,
  Other), **Unfinished**, **Finished** and **Queues**. The search box filters by name or link.
- Double-click a finished download to open it (programs and scripts ask first). Right-click
  for *Open folder*, *Copy link*, *Refresh link...*, *Download again* and *Move to queue*.
- **Delete** (toolbar or the Del key) removes downloads from the list and, if you tick it,
  the files too.
- **Details** shows the live speed graph and a map of each connection's progress.
- Closing the window keeps OpenDM in the tray; use **Quit** in the tray menu to exit.

## Queues and schedules

**Queues** lets you create queues, set how many downloads run at once, a start and stop time
and days, and what to do when the queue is done (nothing, sleep or shut down; you get a
60-second countdown you can cancel).

## Speed limits and proxy

*Settings -> Connections*: a total speed limit and the number of connections per download
and per website. *Settings -> Proxy*: Windows' proxy (default), no proxy, or your own HTTP or
SOCKS proxy.

## Video and audio

Paste a page link (YouTube, Vimeo and many more sites through
[yt-dlp](https://github.com/yt-dlp/yt-dlp)) and OpenDM shows a quality picker: best
quality or a height cap; the format MP4/MKV/WebM, or MP3/M4A for audio only; subtitles and the
thumbnail. For a playlist you choose which items to download. A link to one video inside a
playlist or YouTube Mix downloads just that video; *Show the whole playlist...* lists them
all.

The first time, OpenDM asks to download yt-dlp and FFmpeg (about 130 MB) from their official
sources and checks their published checksums. They live in the `tools` folder inside the
install folder. *Settings -> Tools* shows their versions, updates yt-dlp (sites change often,
so keep it current; a weekly check can remind you) or lets you use copies you already have.
If the tools go missing, video downloads wait and OpenDM offers to download them again.

DRM-protected video (Netflix, Disney+ and similar) is not supported.

## Browser

With the extension set up (see [INSTALL.md](INSTALL.md)):

- Downloads you start in Chrome or Edge go to OpenDM (with the site's cookies, so links that
  need you to be logged in work). Hold **Alt** while clicking a link to let the browser
  download it itself. The extension's options set a minimum size and file types.
- Right-click a link, video or page: *Download with OpenDM*, *Download all links with
  OpenDM* (you pick which ones) or *Download video on this page with OpenDM*.
- A **Download** button over videos and the toolbar icon (with a count of media found on the
  page) send videos to OpenDM's quality picker.

## Command line

`opendm-cli` is next to `OpenDM.exe`:

```
opendm-cli get https://example.com/file.zip -o D:\Downloads
opendm-cli get "https://www.youtube.com/watch?v=..." --media --quality audio-mp3
opendm-cli list
opendm-cli pause <id>      opendm-cli resume <id>      opendm-cli remove <id>
```

With OpenDM running, commands go to the app; `get --standalone` downloads in the console
window without it. `opendm-cli --help` lists every option.

## Updates, logs and getting help

- *Settings -> Updates*: turn the update check on or off, include test versions, or
  *Check now*.
- *Settings -> General -> Export diagnostics* saves a ZIP with OpenDM's logs, settings and
  versions (links, cookies and passwords removed) to attach to a
  [bug report](https://github.com/Indrajit147/OpenDM/issues/new/choose).
- More answers in the [FAQ](FAQ.md).
