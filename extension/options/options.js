// Options page: edits chrome.storage.sync through the same normalizer the worker uses.
import { DEFAULTS, normalizeSettings } from "../lib/settings.js";

const $ = (id) => document.getElementById(id);

function show(s) {
  $("takeover").checked = s.takeover;
  $("minSizeMB").value = s.minSizeMB;
  $("extensions").value = s.extensions.join(" ");
  $("videoButton").checked = s.videoButton;
  $("notifyFailures").checked = s.notifyFailures;
}

function say(text) {
  $("result").textContent = text;
}

show(normalizeSettings(await chrome.storage.sync.get(null)));

$("save").addEventListener("click", async () => {
  const s = normalizeSettings({
    takeover: $("takeover").checked,
    minSizeMB: $("minSizeMB").value,
    extensions: $("extensions").value.split(/[\s,]+/).filter(Boolean),
    videoButton: $("videoButton").checked,
    notifyFailures: $("notifyFailures").checked,
  });
  await chrome.storage.sync.set(s);
  show(s);
  say("Saved. Reload open tabs for the video button setting.");
});

$("reset").addEventListener("click", async () => {
  await chrome.storage.sync.clear();
  show(normalizeSettings(DEFAULTS));
  say("Defaults restored.");
});

$("test").addEventListener("click", async () => {
  say("Testing…");
  const reply = await chrome.runtime.sendMessage({ type: "status" });
  say(reply?.ok ? "OpenDM is running and connected." : `Not connected: ${reply?.message || "unknown error"}`);
});
