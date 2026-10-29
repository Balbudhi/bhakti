const CACHE = "bhakti-shell-v46";
const SHELL = [
  "/", "/index.html", "/manifest.webmanifest",
  "/assets/site.css", "/assets/song.css", "/assets/app.css",
  "/assets/library.js", "/assets/song.js", "/assets/queue.js", "/assets/app.js", "/assets/pwa.js",
  "/assets/media-session.js", "/assets/owner-entry.js", "/assets/icon-192.png",
  "/assets/player-icons.svg", "/data/songs.js", "/assets/favicon.svg", "/assets/favicon.png",
];

self.addEventListener("install", event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())
));
self.addEventListener("activate", event => event.waitUntil(
  caches.keys()
    .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim())
));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  const pathname = url.pathname;
  if (event.request.method !== "GET" || /\.(?:m4a|webm|ogg|mp3|wav|flac)$/.test(pathname)) return;
  // Never restore a stale reader document while the listener is online. Long
  // pages are deliberately rendered incrementally, and replaying an old cached
  // shell after Home → search can revive the pre-incremental implementation on
  // iOS. Keep the shell only as an offline last resort.
  if (event.request.mode === "navigate" && url.origin === self.location.origin) {
    event.respondWith(
      fetch(event.request, { cache: "no-store" })
        .catch(() => caches.match("/").then(response => response || Response.error()))
    );
    return;
  }
  // Shell URLs carry release queries in HTML, while installation precaches
  // their bare paths. Share those keys so the first offline launch works even
  // before a controlled online visit. Fetch still uses the original release URL;
  // query parameters outside this explicit same-origin shell stay significant.
  const cacheKey = url.origin === self.location.origin && SHELL.includes(pathname)
    ? pathname : event.request;
  event.respondWith(
    fetch(event.request, { cache: "no-store" })
      .then(response => {
        if (response.ok && url.origin === self.location.origin) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE).then(cache => cache.put(cacheKey, copy)));
        }
        return response;
      })
      .catch(() => caches.match(cacheKey))
  );
});
