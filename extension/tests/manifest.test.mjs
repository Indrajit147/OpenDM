// The manifest's key gives the fixed extension ID the native host allows, and every file it
// names exists.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const root = new URL("../", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", root), "utf8"));

test("key gives the extension ID registered for the native host", () => {
  const der = Buffer.from(manifest.key, "base64");
  const hex = createHash("sha256").update(der).digest("hex").slice(0, 32);
  const id = [...hex].map((c) => String.fromCharCode(97 + parseInt(c, 16))).join("");
  assert.equal(id, "pjkejmcidaikllfpgmfginpahcockofb");
});

test("every file named in the manifest exists", () => {
  const files = [
    manifest.background.service_worker,
    manifest.action.default_popup,
    manifest.options_ui.page,
    ...manifest.content_scripts.flatMap((c) => c.js),
    ...Object.values(manifest.icons),
    ...Object.values(manifest.action.default_icon),
  ];
  for (const file of files) assert.ok(existsSync(new URL(file, root)), file);
});

test("permissions are the documented set", () => {
  assert.deepEqual([...manifest.permissions].sort(), [
    "contextMenus", "cookies", "downloads", "nativeMessaging", "notifications", "storage", "webRequest",
  ]);
});
