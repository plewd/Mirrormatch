// Service worker: makes Mirrormatch installable and playable offline after one visit.
// - vendor/ (the pinned Pyodide runtime and Blockly) is served from the cache straight away and
//   refreshed in the background, since it only changes when its pinned version does.
// - Everything else is network-first, so a new deploy shows up on the next load; the cached copy
//   is only used when the network fails.
// The file list to save comes from build/files.json, written by `python -m arena.web build`.
// Bump the cache names to drop old caches (e.g. if the cached layout ever changes).
const VENDOR = "mm-vendor-v1";
const APP = "mm-app-v1";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const files = await (await fetch("build/files.json", { cache: "no-cache" })).json();
    const vendor = await caches.open(VENDOR);
    const app = await caches.open(APP);
    await Promise.all([
      vendor.addAll(files.filter((f) => f.startsWith("vendor/"))),
      app.addAll(["./", ...files.filter((f) => !f.startsWith("vendor/"))]),
    ]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name !== VENDOR && name !== APP) await caches.delete(name);
    await self.clients.claim();
  })());
});

async function vendorFirst(request) {
  const cache = await caches.open(VENDOR);
  const cached = await cache.match(request);
  const refresh = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => cached);
  return cached || refresh;
}

async function networkFirst(request) {
  const cache = await caches.open(APP);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    // Offline: the saved copy (pages ignore the query, so "?auto=play" still opens the app).
    const cached = await cache.match(request, { ignoreSearch: request.mode === "navigate" });
    return cached || (request.mode === "navigate" ? cache.match("./") : Response.error());
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  const path = new URL(request.url).pathname;
  event.respondWith(path.includes("/vendor/") ? vendorFirst(request) : networkFirst(request));
});
