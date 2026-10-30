// Build a Cookie header from chrome.cookies.getAll() results for one URL.

const UNSAFE = /[;\r\n\t\0]/;

export function cookieHeader(cookies) {
  const usable = (cookies || []).filter(
    (c) => c && typeof c.name === "string" && c.name && !UNSAFE.test(c.name) && !UNSAFE.test(c.value ?? ""),
  );
  if (!usable.length) return undefined;
  // RFC 6265 5.4: cookies with longer paths first.
  usable.sort((a, b) => (b.path || "").length - (a.path || "").length);
  return usable.map((c) => `${c.name}=${c.value}`).join("; ");
}
