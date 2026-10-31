// OpenDM Integration: content script. Reads nothing unless asked:
// - remembers Alt+click on a link (so the browser keeps that download),
// - lists the page's links when the user chooses "Download all links with OpenDM",
// - shows a small Download button over videos (can be turned off in the options).
(() => {
  if (window.top !== window || window.__opendmLoaded) return;
  window.__opendmLoaded = true;

  document.addEventListener(
    "click",
    (event) => {
      if (event.altKey && event.target instanceof Element && event.target.closest("a[href]")) {
        chrome.runtime.sendMessage({ type: "skip-next" }).catch(() => {});
      }
    },
    true,
  );

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "collect-links") {
      const urls = Array.from(document.querySelectorAll("a[href]"), (a) => a.href);
      sendResponse({ urls, title: document.title });
    }
  });

  chrome.storage.sync.get({ videoButton: true }).then(({ videoButton }) => {
    if (videoButton) setUpVideoButton();
  });

  function setUpVideoButton() {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;z-index:2147483647;display:none;top:0;left:0;";
    const shadow = host.attachShadow({ mode: "closed" });
    const button = document.createElement("button");
    button.textContent = "Download";
    button.title = "Download this video with OpenDM";
    button.style.cssText = [
      "font:600 12px/1 system-ui,sans-serif", "padding:6px 10px", "border:0", "border-radius:6px",
      "background:#1f8577", "color:#fff", "cursor:pointer", "opacity:.92",
      "box-shadow:0 1px 4px rgba(0,0,0,.4)",
    ].join(";");
    shadow.appendChild(button);
    document.documentElement.appendChild(host);
    let current = null;
    let hideTimer = 0;

    function place(video) {
      const rect = video.getBoundingClientRect();
      if (rect.width < 160 || rect.height < 90) return hide();
      current = video;
      host.style.top = `${Math.max(rect.top + 8, 0)}px`;
      host.style.left = `${Math.max(rect.right - 100, 0)}px`;
      host.style.display = "block";
    }
    function hide() {
      host.style.display = "none";
      current = null;
    }
    document.addEventListener(
      "mouseover",
      (event) => {
        const video = event.target instanceof Element ? event.target.closest("video") : null;
        if (video) {
          clearTimeout(hideTimer);
          place(video);
        } else if (event.target !== host) {
          clearTimeout(hideTimer);
          hideTimer = setTimeout(hide, 800);
        }
      },
      true,
    );
    host.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    window.addEventListener("scroll", () => current && place(current), { passive: true });
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!current) return;
      button.textContent = "Sending…";
      chrome.runtime
        .sendMessage({ type: "video", src: current.currentSrc || current.src })
        .then((reply) => reply?.text || "OpenDM could not take it", () => "OpenDM could not take it")
        .then((text) => {
          button.textContent = text;
          setTimeout(() => (button.textContent = "Download"), 3000);
        });
    });
  }
})();
