# Store listings: Chrome Web Store and Microsoft Edge Add-ons

Everything needed to publish the **OpenDM Integration** extension. Publishing is the
maintainer's decision and needs their own accounts:

- **Chrome Web Store:** a developer account with a one-time registration fee (US$5 when
  Google introduced it; the dashboard shows the current amount).
  [Register](https://developer.chrome.com/docs/webstore/register).
- **Edge Add-ons:** free, through Partner Center (a personal Microsoft or GitHub account);
  step by step at the end of this page.
  [Register](https://learn.microsoft.com/microsoft-edge/extensions/publish/create-dev-account).

## Package

```
.venv\Scripts\python.exe scripts\package_extension.py
```

writes `build\store\opendm-extension-<version>.zip`: the `extension` folder without the
development `key` (each store assigns its own extension ID), without tests, and with the
app's version. Images are in `store\images` (`scripts\store_assets.py` redraws them).

## After the first approval: tell OpenDM the new IDs

The stores give the extension new IDs. Add each one to `EXTENSION_IDS` in
`src/opendm/core/branding.py`, release a new OpenDM, and the browser setup
(Settings -> Browser) allows them. Until then only the unpacked extension can talk to the app.

## Listing

**Name:** OpenDM Integration

**Summary (132 characters max):**
Send downloads and videos from Chrome or Edge to OpenDM, the free, open-source download manager for Windows.

**Category:** Productivity (Chrome: Tools)

**Description:**

> OpenDM Integration connects your browser to OpenDM, a free and open-source download
> manager for Windows (GPL-3.0). It needs the OpenDM app: https://github.com/Indrajit147/OpenDM
>
> - Downloads you start go to OpenDM: faster multi-connection downloads that resume after a
>   break, with the site's cookies so downloads behind a login keep working. Hold Alt while
>   clicking to let the browser download instead. Choose file types and a minimum size.
> - Right-click "Download with OpenDM" on links, videos and audio; "Download all links" lets
>   you pick links from a page.
> - A Download button on videos, and the toolbar icon lists video and audio found on the
>   page, opening OpenDM's quality picker (through yt-dlp). DRM-protected content is not
>   supported.
>
> No ads, no tracking, no account. The extension talks only to the OpenDM app on your
> computer and makes no network requests of its own. Privacy details:
> https://github.com/Indrajit147/OpenDM/blob/main/docs/PRIVACY.md

**Images:** `images/icon-128.png`, `images/promo-440x280.png` (small promo tile),
`images/screenshot-*-1280x800.png`.

**Website / support:** https://github.com/Indrajit147/OpenDM ·
https://github.com/Indrajit147/OpenDM/issues

**Privacy policy URL:** https://github.com/Indrajit147/OpenDM/blob/main/docs/PRIVACY.md

## Privacy practices (Chrome dashboard answers)

**Single purpose:** Hand downloads, links and videos from the browser to the OpenDM download
manager app on the same computer.

**Permission justifications:**

| Permission | Justification |
|---|---|
| `downloads` | Notice downloads the user starts, pause them, and cancel them once OpenDM has taken them over. |
| `nativeMessaging` | The only channel to the OpenDM app on the same computer. |
| `contextMenus` | "Download with OpenDM", "Download all links" and "Download video on this page" menu items. |
| `cookies` | Read the cookies of the site a download comes from, so files behind a login download in OpenDM; sent only to the local app, for that download. |
| `storage` | The user's extension settings, and the list of media found in open tabs (session only). |
| `webRequest` | Read response headers (content type and length) to recognise video, audio and stream manifests on a page. Bodies are not read; requests are not modified or blocked. |
| `notifications` | Tell the user when OpenDM could not take over a download (can be turned off). |
| Host access (`<all_urls>`) | Needed for the cookies of any download site, media detection on any page, and the video button. |

**Remote code:** No. All code is in the package.

**Data usage:** The extension handles *website content* (links and page addresses) and
*authentication information* (cookies of the download's site) only to hand a download the
user started to the OpenDM app on the same computer. Nothing is sold, transferred to third
parties, used for advertising or creditworthiness, or sent anywhere else. Tick the
certifications accordingly.

## Edge Add-ons: step by step

1. **Register (free, once).** Go to
   [Partner Center for Edge](https://partner.microsoft.com/dashboard/microsoftedge/overview)
   and sign in with a personal Microsoft or GitHub account. Choose to register as an
   *Individual*, fill in your name and contact details, accept the Microsoft Edge Developer
   Agreement and wait for the confirmation email.
2. **Build the package:** `.venv\Scripts\python.exe scripts\package_extension.py` ->
   `build\store\opendm-extension-<version>.zip`.
3. **Create the submission:** Partner Center -> Microsoft Edge -> **Create new extension** ->
   upload the ZIP.
4. **Availability:** Public, all markets.
5. **Properties:** Category *Productivity*; privacy policy URL (above); website and support
   URLs (above); "Does this extension access personal information?" -> *Yes* (cookies and page
   links, only passed to the local OpenDM app; see the privacy practices above); mature
   content -> No.
6. **Store listings (English):** the description and summary above as the description and
   short description, `images/icon-300.png` as the store logo (300x300), `images/promo-440x280.png` as the
   small promo tile, and the three `images/screenshot-*-1280x800.png`.
7. **Notes for certification:**
   *"Companion extension for the OpenDM desktop app (open source, GPL-3.0,
   https://github.com/Indrajit147/OpenDM). It uses native messaging to hand downloads to the
   app. To test: install OpenDM from https://github.com/Indrajit147/OpenDM/releases/latest,
   open Settings > Browser and click Set up, then start a download in Edge. Without the app
   the popup shows 'App not installed' with a link to get it."*
8. **Before publishing, look for the ID.** After the upload, Partner Center usually shows the
   extension's ID (32 letters a-p) on the extension's overview or "Extension identity"
   section. If it is there, send it to Claude first: OpenDM 1.0.1 with that ID is released
   before certification, so Microsoft's tester sees "Connected" instead of "Update OpenDM".
9. **Publish** and wait for certification (Microsoft quotes up to 7 business days).
10. **When it is live** (if the ID was not sent in step 8): open the listing; its address ends with the extension ID (32 letters
    a-p). Send it to Claude: it goes into `EXTENSION_IDS`, OpenDM 1.0.1 is released, and users
    who update and click *Repair* in Settings -> Browser can use the store version. Until 1.0.1
    is installed, the store version shows "Update OpenDM".
