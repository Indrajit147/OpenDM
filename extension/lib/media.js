// Recognise media from response headers (webRequest, non-blocking). MV3 cannot read bodies.

const MANIFEST_TYPES = ["application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "application/dash+xml"];
const SEGMENT = /\.(ts|m4s|m4f|cmfv|cmfa|aac|vtt|webvtt)$/i;
const MIN_FILE = 512 * 1024; // smaller video/audio responses are usually previews or pieces
export const MAX_ITEMS = 100;

function header(headers, name) {
  const found = (headers || []).find((h) => h.name.toLowerCase() === name);
  return found ? String(found.value || "") : "";
}

export function classifyResponse(url, headers) {
  let path;
  try {
    path = new URL(url).pathname.toLowerCase();
  } catch {
    return null;
  }
  const mime = header(headers, "content-type").split(";")[0].trim().toLowerCase();
  const length = parseInt(header(headers, "content-length"), 10);
  const size = Number.isFinite(length) ? length : null;
  if (path.endsWith(".m3u8") || path.endsWith(".mpd") || MANIFEST_TYPES.includes(mime)) {
    return { kind: "manifest", mime, size };
  }
  const isVideo = mime.startsWith("video/");
  const isAudio = mime.startsWith("audio/");
  if (!isVideo && !isAudio) return null;
  if (SEGMENT.test(path) || mime === "video/mp2t" || mime === "video/iso.segment") return null;
  if (size !== null && size < MIN_FILE) return null;
  return { kind: isVideo ? "video" : "audio", mime, size };
}

/**
 * Newest first, unique by URL, at most MAX_ITEMS. Seeing a known URL again (live streams
 * re-fetch their manifest every few seconds) leaves the list as it is, so it does not jump.
 */
export function addDetected(list, item, max = MAX_ITEMS) {
  if (list.some((i) => i.url === item.url)) return list;
  return [item, ...list].slice(0, max);
}
