// OpenDM Integration: service worker (Manifest V3).
// Talks to the app only through Native Messaging; sends data only when the user acts or a
// download is taken over (see docs/PRIVACY.md).
import { cookieHeader } from "./lib/cookies.js";
import { cleanLinks } from "./lib/links.js";
import { addDetected, classifyResponse } from "./lib/media.js";
import { downloadMessage, linksMessage } from "./lib/messages.js";
import { normalizeSettings } from "./lib/settings.js";
import { nameFromUrl, shouldTakeOver } from "./lib/takeover.js";

const HOST = "io.github.indrajit147.opendm";
const SKIP_MS = 3000; // Alt+click lets the browser keep the next download for this long

// --- helpers ----------------------------------------------------------------------------------

async function settings() {
  return normalizeSettings(await chrome.storage.sync.get(null));
}

export async function sendToOpenDM(message) {
  try {
    const reply = await chrome.runtime.sendNativeMessage(HOST, message);
    return reply || { ok: false, error: "unavailable", message: "no reply from OpenDM" };
  } catch (error) {
    return { ok: false, error: "unavailable", message: String(error?.message || error) };
  }
}

async function cookiesFor(url) {
  try {
    return cookieHeader(await chrome.cookies.getAll({ url }));
  } catch {
    return undefined;
  }
}

async function notify(title, message) {
  if (!(await settings()).notifyFailures) return;
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
  });
}

async function capture({ url, pageUrl, pageTitle, referrer, filename, fileSize, media }) {
  let message;
  try {
    message = downloadMessage({
      url, pageUrl, pageTitle, referrer, filename, fileSize, media,
      userAgent: navigator.userAgent,
      cookies: await cookiesFor(url),
    });
  } catch (error) {
    await notify("OpenDM", error.message);
    return { ok: false, error: "invalid", message: error.message };
  }
  const reply = await sendToOpenDM(message);
  if (!reply.ok) await notify("OpenDM", reply.message || "OpenDM did not accept the link.");
  return reply;
}

// --- download takeover --------------------------------------------------------------------------

chrome.downloads.onCreated.addListener(async (item) => {
  const { skipUntil = 0 } = await chrome.storage.session.get("skipUntil");
  if (!shouldTakeOver(item, await settings(), Date.now(), skipUntil)) return;
  const url = item.finalUrl || item.url;
  if (!/^https?:\/\//i.test(url)) return; // blob:, data: and the like stay in the browser
  try {
    await chrome.downloads.pause(item.id);
  } catch {
    return; // already finished or gone: leave it to the browser
  }
  const message = downloadMessage({
    url,
    referrer: item.referrer,
    pageUrl: item.referrer,
    filename: nameFromUrl(url) || undefined,
    fileSize: item.fileSize > 0 ? item.fileSize : undefined,
    userAgent: navigator.userAgent,
    cookies: await cookiesFor(url),
  });
  const reply = await sendToOpenDM(message);
  if (reply.ok) {
    await chrome.downloads.cancel(item.id).catch(() => {});
    await chrome.downloads.erase({ id: item.id }).catch(() => {});
  } else {
    await chrome.downloads.resume(item.id).catch(() => {});
    await notify("OpenDM is not available", "The browser is downloading the file instead.");
  }
});

// --- context menu ---------------------------------------------------------------------------------

function createMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "opendm-link", title: "Download with OpenDM", contexts: ["link"] });
    chrome.contextMenus.create({ id: "opendm-media", title: "Download with OpenDM", contexts: ["video", "audio"] });
    chrome.contextMenus.create({ id: "opendm-all-links", title: "Download all links with OpenDM", contexts: ["page"] });
    chrome.contextMenus.create({ id: "opendm-page-video", title: "Download video on this page with OpenDM", contexts: ["page"] });
  });
}

chrome.runtime.onInstalled.addListener(createMenus);
chrome.runtime.onStartup.addListener(createMenus);

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const page = { pageUrl: info.pageUrl || tab?.url, pageTitle: tab?.title };
  if (info.menuItemId === "opendm-link") {
    await capture({ url: info.linkUrl, referrer: page.pageUrl, ...page });
  } else if (info.menuItemId === "opendm-media") {
    await handleVideo({ src: info.srcUrl, ...page });
  } else if (info.menuItemId === "opendm-page-video") {
    await capture({ url: page.pageUrl, media: true, ...page });
  } else if (info.menuItemId === "opendm-all-links" && tab?.id !== undefined) {
    let found;
    try {
      found = await chrome.tabs.sendMessage(tab.id, { type: "collect-links" });
    } catch {
      await notify("OpenDM", "Links cannot be read on this page.");
      return;
    }
    const urls = cleanLinks(found?.urls, page.pageUrl);
    if (!urls.length) {
      await notify("OpenDM", "No links found on this page.");
      return;
    }
    const reply = await sendToOpenDM(linksMessage(urls, page.pageUrl, found?.title || page.pageTitle));
    if (!reply.ok) await notify("OpenDM", reply.message || "OpenDM did not accept the links.");
  }
});

/** <video>/<audio>: a real file URL is downloaded directly; anything else (blob:, streams)
 *  goes to yt-dlp through the page URL - a blob: URL is not a file. */
async function handleVideo({ src, pageUrl, pageTitle }) {
  const direct = typeof src === "string" && /^https?:\/\//i.test(src) && !/\.(m3u8|mpd)(\?|$)/i.test(src);
  if (direct) return capture({ url: src, referrer: pageUrl, pageUrl, pageTitle });
  return capture({ url: pageUrl, media: true, pageUrl, pageTitle });
}

// --- messages from the content script and popup ------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    switch (message?.type) {
      case "skip-next":
        await chrome.storage.session.set({ skipUntil: Date.now() + SKIP_MS });
        return { ok: true };
      case "video":
        return handleVideo({ src: message.src, pageUrl: sender.tab?.url, pageTitle: sender.tab?.title });
      case "download-detected":
        return message.item.kind === "manifest"
          ? capture({ url: message.pageUrl, media: true, pageUrl: message.pageUrl, pageTitle: message.pageTitle })
          : capture({ url: message.item.url, referrer: message.pageUrl, pageUrl: message.pageUrl, pageTitle: message.pageTitle });
      case "download-page":
        return capture({ url: message.pageUrl, media: true, pageUrl: message.pageUrl, pageTitle: message.pageTitle });
      case "status":
        return sendToOpenDM({ type: "status" });
      case "detected":
        return { items: await detectedFor(message.tabId) };
      default:
        return { ok: false, error: "unknown message" };
    }
  })().then(sendResponse);
  return true; // async response
});

// --- media detection ----------------------------------------------------------------------------

const key = (tabId) => `media:${tabId}`;

async function detectedFor(tabId) {
  const stored = await chrome.storage.session.get(key(tabId));
  return stored[key(tabId)] || [];
}

async function setDetected(tabId, items) {
  await chrome.storage.session.set({ [key(tabId)]: items });
  chrome.action.setBadgeText({ tabId, text: items.length ? String(items.length) : "" });
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#1f8577" });
}

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    const found = classifyResponse(details.url, details.responseHeaders);
    if (!found) return;
    (async () => {
      const list = await detectedFor(details.tabId);
      const next = addDetected(list, { url: details.url, ...found, name: nameFromUrl(details.url) });
      if (next !== list) await setDetected(details.tabId, next);
    })();
  },
  { urls: ["http://*/*", "https://*/*"], types: ["media", "xmlhttprequest", "other", "object"] },
  ["responseHeaders"],
);

chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url) setDetected(tabId, []); // a new page: forget the old one's media
});
chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove(key(tabId)));
