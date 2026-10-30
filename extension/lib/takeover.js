// Decide whether a browser download should be handed to OpenDM.

const MB = 1024 * 1024;

export function nameFromUrl(url) {
  try {
    const path = new URL(url).pathname;
    return decodeURIComponent(path.slice(path.lastIndexOf("/") + 1));
  } catch {
    return "";
  }
}

export function extensionOf(name) {
  const lower = name.toLowerCase();
  const base = lower.slice(Math.max(lower.lastIndexOf("/"), lower.lastIndexOf("\\")) + 1);
  const parts = base.split(".");
  if (parts.length < 2 || !parts[0]) return "";
  const last = parts[parts.length - 1];
  if (parts.length >= 3 && parts[parts.length - 2] === "tar") return `tar.${last}`;
  return last;
}

function isWebUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

/**
 * item: a chrome.downloads.DownloadItem; settings: normalizeSettings(); now/skipUntil in ms.
 */
export function shouldTakeOver(item, settings, now, skipUntil) {
  if (!settings.takeover || item.byExtensionId) return false;
  if (skipUntil && now < skipUntil) return false; // the user Alt+clicked the link
  const url = item.finalUrl || item.url;
  if (!isWebUrl(url) || !isWebUrl(item.url)) return false; // blob:, data:, file:, ...
  const name = item.filename || nameFromUrl(url);
  if (!settings.extensions.includes(extensionOf(name))) return false;
  const size = item.fileSize > 0 ? item.fileSize : item.totalBytes > 0 ? item.totalBytes : -1;
  if (size >= 0 && size < settings.minSizeMB * MB) return false;
  return true;
}
