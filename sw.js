const CACHE = "bhakti-shell-v5";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/assets/site.css", "/assets/library.js", "/data/songs.js", "/assets/favicon.svg", "/assets/favicon.png"];

self.addEventListener("install", event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())
));
self.addEventListener("activate", event => event.waitUntil(
  caches.keys()
    .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim())
));
self.addEventListener("fetch", event => {
  const pathname = new URL(event.request.url).pathname;
  if (event.request.method !== "GET" || /\.(?:m4a|webm|ogg|mp3|wav|flac)$/.test(pathname)) return;
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok && new URL(event.request.url).origin === self.location.origin) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE).then(cache => cache.put(event.request, copy)));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
