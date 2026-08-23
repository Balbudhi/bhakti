const CACHE = "bhakti-shell-v23";
const SHELL = [
  "/", "/index.html", "/manifest.webmanifest",
  "/assets/site.css", "/assets/song.css", "/assets/app.css",
  "/assets/library.js", "/assets/song.js", "/assets/queue.js", "/assets/app.js", "/assets/pwa.js",
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
  // Playlist state lives in the query string, but every route serves the same
  // static shell. Cache navigations by pathname so arbitrary playlist URLs do
  // not create duplicate cache entries and can reuse the canonical page offline.
  const cacheKey = event.request.mode === "navigate" && url.origin === self.location.origin
    ? new Request(url.origin + pathname)
    : event.request;
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
