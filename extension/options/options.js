// Options page: edits chrome.storage.sync through the same normalizer the worker uses.
import { DEFAULTS, normalizeSettings } from "../lib/settings.js";
import { connectionState } from "../lib/status.js";

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

async function test() {
  say("Testing…");
  const reply = await chrome.runtime.sendMessage({ type: "status" });
  const info = connectionState(reply);
  say(info.text);
  if (info.link) {
    const link = document.createElement("a");
    link.href = info.link;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = " Get OpenDM";
    $("result").append(link);
  }
}

$("test").addEventListener("click", test);
test(); // opened after a failed click: say at once what is wrong
