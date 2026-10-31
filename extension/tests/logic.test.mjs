// Unit tests for the extension's pure logic. Run: node --test extension/tests/
import assert from "node:assert/strict";
import { test } from "node:test";

import { cookieHeader } from "../lib/cookies.js";
import { cleanLinks } from "../lib/links.js";
import { addDetected, classifyResponse } from "../lib/media.js";
import { downloadMessage, linksMessage } from "../lib/messages.js";
import { GET_OPENDM_URL, buttonText, connectionState, leaveToBrowser, reachState } from "../lib/status.js";
import { DEFAULTS, normalizeSettings } from "../lib/settings.js";
import { extensionOf, nameFromUrl, shouldTakeOver } from "../lib/takeover.js";

const MB = 1024 * 1024;
const item = (over = {}) => ({
  url: "https://example.com/files/setup.exe",
  finalUrl: "https://cdn.example.com/files/setup.exe",
  filename: "",
  fileSize: 50 * MB,
  totalBytes: 50 * MB,
  ...over,
});

test("extensionOf handles double extensions, query strings and case", () => {
  assert.equal(extensionOf("Archive.TAR.GZ"), "tar.gz");
  assert.equal(extensionOf("movie.mkv"), "mkv");
  assert.equal(extensionOf("README"), "");
  assert.equal(nameFromUrl("https://h/a/b%20c.zip?x=1#f"), "b c.zip");
  assert.equal(nameFromUrl("https://h/"), "");
});

test("takes over listed types of at least the minimum size", () => {
  const s = normalizeSettings({});
  assert.equal(shouldTakeOver(item(), s, 0, 0), true);
  assert.equal(shouldTakeOver(item({ fileSize: 10 }), s, 0, 0), false); // too small
  assert.equal(shouldTakeOver(item({ fileSize: -1, totalBytes: -1 }), s, 0, 0), true); // unknown size
  assert.equal(shouldTakeOver(item({ finalUrl: "https://h/page.html", url: "https://h/page.html" }), s, 0, 0), false);
  assert.equal(shouldTakeOver(item({ filename: "C:\\Users\\x\\Downloads\\pack.zip" }), s, 0, 0), true);
});

test("never takes over blob:, data:, other extensions' downloads, or when disabled", () => {
  const s = normalizeSettings({});
  assert.equal(shouldTakeOver(item({ url: "blob:https://h/1", finalUrl: "blob:https://h/1", filename: "a.zip" }), s, 0, 0), false);
  assert.equal(shouldTakeOver(item({ url: "data:application/zip;base64,AA", finalUrl: "" , filename: "a.zip"}), s, 0, 0), false);
  assert.equal(shouldTakeOver(item({ byExtensionId: "abc" }), s, 0, 0), false);
  assert.equal(shouldTakeOver(item(), normalizeSettings({ takeover: false }), 0, 0), false);
});

test("Alt+click skips the next takeover for a few seconds", () => {
  const s = normalizeSettings({});
  assert.equal(shouldTakeOver(item(), s, 1000, 3000), false);
  assert.equal(shouldTakeOver(item(), s, 4000, 3000), true);
});

test("settings are normalized and validated", () => {
  const s = normalizeSettings({ minSizeMB: "-5", extensions: [".ZIP", " iso ", "", "bad ext", 7] });
  assert.equal(s.minSizeMB, 0);
  assert.deepEqual(s.extensions, ["zip", "iso"]);
  assert.equal(normalizeSettings({ minSizeMB: 2.5 }).minSizeMB, 2.5);
  assert.ok(DEFAULTS.extensions.includes("zip") && DEFAULTS.extensions.includes("mp4"));
});

test("cookie header from chrome.cookies objects", () => {
  const header = cookieHeader([
    { name: "a", value: "1", path: "/" },
    { name: "session", value: "s3", path: "/members" },
    { name: "bad\nname", value: "x", path: "/" },
    { name: "b", value: "with;semicolon", path: "/" },
  ]);
  assert.equal(header, "session=s3; a=1"); // longer paths first; unsafe cookies dropped
  assert.equal(cookieHeader([]), undefined);
});

test("media detection from response headers", () => {
  const h = (type, length) => [{ name: "Content-Type", value: type }, ...(length ? [{ name: "content-length", value: String(length) }] : [])];
  assert.deepEqual(classifyResponse("https://h/live/index.m3u8", []), { kind: "manifest", mime: "", size: null });
  assert.equal(classifyResponse("https://h/x", h("application/dash+xml")).kind, "manifest");
  assert.equal(classifyResponse("https://h/clip.mp4", h("video/mp4", 5 * MB)).kind, "video");
  assert.equal(classifyResponse("https://h/song.mp3", h("audio/mpeg", 3 * MB)).kind, "audio");
  assert.equal(classifyResponse("https://h/seg001.ts", h("video/mp2t", 400000)), null); // segment
  assert.equal(classifyResponse("https://h/chunk-3.m4s", h("video/iso.segment", 300000)), null);
  assert.equal(classifyResponse("https://h/tiny.mp4", h("video/mp4", 2000)), null); // too small
  assert.equal(classifyResponse("https://h/page", h("text/html")), null);
});

test("detected media list: newest first, no duplicates, capped", () => {
  let list = [];
  list = addDetected(list, { url: "https://h/a.m3u8", kind: "manifest" });
  list = addDetected(list, { url: "https://h/b.mp4", kind: "video" });
  list = addDetected(list, { url: "https://h/a.m3u8", kind: "manifest" });
  assert.deepEqual(list.map((i) => i.url), ["https://h/b.mp4", "https://h/a.m3u8"]);
  for (let i = 0; i < 150; i++) list = addDetected(list, { url: `https://h/${i}.mp4`, kind: "video" });
  assert.equal(list.length, 100);
});

test("download message carries only set, well-typed fields", () => {
  const msg = downloadMessage({
    url: "https://h/a.zip", pageUrl: "https://h/", pageTitle: "", referrer: undefined,
    userAgent: "UA", cookies: "s=1", filename: "a.zip", fileSize: -1, media: false,
  });
  assert.deepEqual(msg, {
    type: "download", url: "https://h/a.zip", pageUrl: "https://h/", userAgent: "UA",
    cookies: "s=1", filename: "a.zip", fileSize: -1, media: false,
  });
  assert.throws(() => downloadMessage({ url: "javascript:alert(1)" }));
});

test("links: absolute http(s) only, no fragments, no duplicates", () => {
  const links = cleanLinks(
    ["https://h/a.zip#x", "/b.pdf", "javascript:void(0)", "mailto:x@y", "https://h/a.zip", "ftp://h/c"],
    "https://h/dir/page.html",
  );
  assert.deepEqual(links, ["https://h/a.zip", "https://h/b.pdf"]);
  assert.deepEqual(linksMessage(links, "https://h/dir/page.html", "Page"), {
    type: "links", urls: links, pageUrl: "https://h/dir/page.html", pageTitle: "Page",
  });
});

test("connection state: connected, not installed, too old, not running", () => {
  assert.equal(connectionState({ ok: true }).state, "connected");
  const missing = connectionState({ ok: false, message: "Specified native messaging host not found." });
  assert.equal(missing.state, "not-installed");
  assert.equal(missing.link, GET_OPENDM_URL);
  const old = connectionState({ ok: false, message: "Access to the specified native messaging host is forbidden." });
  assert.equal(old.state, "outdated");
  assert.match(old.text, /Repair/);
  const stopped = connectionState({ ok: false, error: "unavailable", message: "OpenDM did not start" });
  assert.equal(stopped.state, "not-running");
  assert.equal(stopped.link, undefined);
  assert.equal(connectionState(undefined).state, "not-running");
});

test("without the app, downloads stay in the browser and buttons say why", () => {
  const missing = { ok: false, error: "unavailable", message: "Specified native messaging host not found." };
  const stopped = { ok: false, error: "unavailable", message: "OpenDM did not start" };
  const refused = { ok: false, error: "invalid", message: "not a web link" }; // the app answered
  assert.equal(reachState({ ok: true }), "connected");
  assert.equal(reachState(refused), "connected");
  assert.equal(reachState(missing), "not-installed");
  assert.equal(reachState(stopped), "not-running");
  assert.equal(leaveToBrowser("not-installed"), true);
  assert.equal(leaveToBrowser("outdated"), true);
  assert.equal(leaveToBrowser("not-running"), false); // it may be started any moment
  assert.equal(leaveToBrowser(undefined), false);
  assert.equal(buttonText({ ok: true }), "Sent to OpenDM");
  assert.equal(buttonText(missing), "OpenDM is not installed");
  assert.equal(buttonText(stopped), "Start OpenDM first");
  assert.equal(buttonText(refused), "OpenDM could not take it");
});
