// Popup: connection status, the media detected on this tab, and a one-click page download.
import { connectionState } from "../lib/status.js";

const $ = (id) => document.getElementById(id);
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
const page = { pageUrl: tab?.url, pageTitle: tab?.title };
const isWeb = /^https?:\/\//i.test(tab?.url || "");

function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024;
    i += 1;
  }
  return `${bytes.toFixed(i ? 1 : 0)} ${units[i]}`;
}

async function send(message, button) {
  button.disabled = true;
  const reply = await chrome.runtime.sendMessage(message);
  button.textContent = reply?.ok ? "Sent" : "Failed";
  button.title = reply?.ok ? "" : reply?.message || "";
  if (reply?.ok) setTimeout(() => window.close(), 600);
  else button.disabled = false;
}

const LABELS = {
  connected: "Connected",
  "not-installed": "App not installed",
  outdated: "Update OpenDM",
  "not-running": "App not running",
};
chrome.runtime.sendMessage({ type: "status" }).then((reply) => {
  const info = connectionState(reply);
  $("status").textContent = LABELS[info.state];
  $("status").classList.add(info.state === "connected" ? "ok" : "bad");
  if (info.state === "connected") return;
  $("status").title = reply?.message || "";
  $("help-text").textContent = info.text;
  $("help").hidden = false;
  if (info.link) {
    $("help-link").href = info.link;
    $("help-link").hidden = false;
  }
});

$("page-video").disabled = !isWeb;
$("page-video").addEventListener("click", (e) => send({ type: "download-page", ...page }, e.target));
$("options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

const { items = [] } = tab ? await chrome.runtime.sendMessage({ type: "detected", tabId: tab.id }) : {};
$("empty").hidden = items.length > 0;
for (const item of items) {
  const li = document.createElement("li");
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = item.kind === "manifest" ? `Stream: ${item.name || item.url}` : item.name || item.url;
  label.title = item.url;
  const meta = document.createElement("span");
  meta.className = "muted";
  meta.textContent = [item.kind, formatSize(item.size)].filter(Boolean).join(" · ");
  const button = document.createElement("button");
  button.textContent = "Download";
  button.addEventListener("click", () => send({ type: "download-detected", item, ...page }, button));
  li.append(label, meta, button);
  $("media").append(li);
}
