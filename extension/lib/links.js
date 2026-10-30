// Clean the links collected from a page for "Download all links with OpenDM".

export const MAX_LINKS = 5000;

export function cleanLinks(hrefs, baseUrl) {
  const seen = new Set();
  for (const href of hrefs || []) {
    let url;
    try {
      url = new URL(href, baseUrl);
    } catch {
      continue;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") continue;
    url.hash = "";
    seen.add(url.href);
    if (seen.size >= MAX_LINKS) break;
  }
  return [...seen];
}
