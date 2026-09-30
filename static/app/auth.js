// Mosaiq auth.js — ES module
// Loads App Bridge, fetches session token, then loads HTMX with token injection.
// See docs/03-shopify-integration.md §2.4

/* global shopify */

let mqToken = await shopify.idToken();

async function mqRefreshToken() {
  mqToken = await shopify.idToken();
}

// Refresh every 30s (tokens expire after 60s)
setInterval(mqRefreshToken, 30_000);

// 1. Register HTMX listeners BEFORE loading HTMX
document.body.addEventListener("htmx:configRequest", (e) => {
  e.detail.headers["Authorization"] = `Bearer ${mqToken}`;
});

document.body.addEventListener("htmx:responseError", async (e) => {
  if (e.detail.xhr.status === 401 && !e.detail.elt.dataset.mqRetried) {
    e.detail.elt.dataset.mqRetried = "1";
    await mqRefreshToken();
    window.htmx.trigger(
      e.detail.elt,
      e.detail.requestConfig.triggeringEvent?.type || "click",
    );
  }
});

// 2. Load HTMX (pinned ESM build from static/vendor/)
const { default: htmx } = await import("/static/vendor/htmx.esm.js");
window.htmx = htmx;
