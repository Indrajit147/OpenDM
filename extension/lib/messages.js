// Messages for the OpenDM Native Messaging host. The host validates them again.

function isWebUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

function compact(obj) {
  return Object.fromEntries(
    Object.entries(obj).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  );
}

export function downloadMessage({ url, pageUrl, pageTitle, referrer, userAgent, cookies, filename, fileSize, media }) {
  if (!isWebUrl(url)) throw new Error("only http and https links can be sent to OpenDM");
  return compact({
    type: "download",
    url,
    pageUrl: isWebUrl(pageUrl) ? pageUrl : undefined,
    pageTitle: typeof pageTitle === "string" ? pageTitle.slice(0, 1000) : undefined,
    referrer: isWebUrl(referrer) ? referrer : undefined,
    userAgent,
    cookies,
    filename: typeof filename === "string" ? filename.slice(0, 255) : undefined,
    fileSize: Number.isInteger(fileSize) ? fileSize : undefined,
    media: Boolean(media),
  });
}

export function linksMessage(urls, pageUrl, pageTitle) {
  return compact({
    type: "links",
    urls,
    pageUrl: isWebUrl(pageUrl) ? pageUrl : undefined,
    pageTitle: typeof pageTitle === "string" ? pageTitle.slice(0, 1000) : undefined,
  });
}
