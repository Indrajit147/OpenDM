// Extension settings (chrome.storage.sync) with defaults and validation.

export const DEFAULTS = Object.freeze({
  takeover: true,
  minSizeMB: 1,
  // File types handed to OpenDM (the app's categories, without everyday web formats).
  extensions: [
    "zip", "rar", "7z", "gz", "tar.gz", "tgz", "bz2", "xz", "iso",
    "exe", "msi", "msix", "apk",
    "mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v",
    "mp3", "m4a", "aac", "flac", "wav", "ogg", "opus",
    "pdf", "epub", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
  ],
  videoButton: true,
  notifyFailures: true,
});

const EXT = /^[a-z0-9]{1,10}(\.[a-z0-9]{1,10})?$/;

export function normalizeSettings(raw) {
  const s = { ...DEFAULTS, ...(raw || {}) };
  const size = Number(s.minSizeMB);
  const extensions = Array.isArray(s.extensions) ? s.extensions : DEFAULTS.extensions;
  return {
    takeover: s.takeover !== false,
    minSizeMB: Number.isFinite(size) && size > 0 ? size : 0,
    extensions: [
      ...new Set(
        extensions
          .filter((e) => typeof e === "string")
          .map((e) => e.trim().toLowerCase().replace(/^\.+/, ""))
          .filter((e) => EXT.test(e)),
      ),
    ],
    videoButton: s.videoButton !== false,
    notifyFailures: s.notifyFailures !== false,
  };
}
