const CACHE = "bhakti-shell-v1";
const SHELL = ["/", "/index.html", "/assets/site.css", "/assets/library.js", "/data/songs.js", "/assets/favicon.png"];

self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  if (event.request.method !== "GET" || event.request.url.endsWith(".m4a")) return;
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});
