// Public assembly supplies a content-addressed manifest. This small fallback
// keeps a source checkout usable without pretending its mutable files are immutable.
const DEVELOPMENT_SHELL = [
  "/", "/index.html", "/manifest.webmanifest", "/assets/site.css", "/assets/song.css",
  "/assets/app.css", "/assets/library.js", "/assets/song.js", "/assets/queue.js",
  "/assets/app.js", "/assets/pwa.js", "/assets/media-session.js", "/assets/owner-entry.js", "/assets/visit.js",
  "/assets/icon-192.png", "/assets/player-icons.svg", "/data/songs.js",
  "/assets/favicon.svg", "/assets/favicon.png",
];
const RELEASE = typeof BHAKTI_RELEASE === "undefined" ? {
  release: "development-v49", shell: DEVELOPMENT_SHELL,
  paths: Object.fromEntries(DEVELOPMENT_SHELL.slice(2).map(path => [path, path])),
  documents: { "/index.html": null },
} : BHAKTI_RELEASE;
const CACHE_PREFIX = "bhakti-release-";
const CACHE = CACHE_PREFIX + RELEASE.release;
const documentPath = path => path.endsWith("/") ? path + "index.html" : path;
const revisionDigest = key => /\?v=([a-f0-9]{64})$/.exec(key)?.[1] || null;

async function matchesDigest(response, digest) {
  if (!digest) return true;
  const bytes = await response.clone().arrayBuffer();
  const actual = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map(byte => byte.toString(16).padStart(2, "0")).join("");
  return actual === digest;
}

async function verifiedFetch(request, digest) {
  const response = await fetch(request, { cache: "no-cache" });
  if (!response.ok || response.type === "opaque") throw new TypeError("Public resource unavailable");
  // A deployment may change between HTML and resource requests. Never label
  // the new bytes as the old revision, including during worker installation.
  if (!await matchesDigest(response, digest)) throw new TypeError("Public resource revision changed");
  return response;
}

async function cachedRevision(key) {
  const names = await caches.keys();
  for (const name of [CACHE, ...names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE).reverse()]) {
    const response = await (await caches.open(name)).match(key);
    if (response) return response;
  }
}

self.addEventListener("install", event => event.waitUntil((async () => {
  const existed = (await caches.keys()).includes(CACHE);
  const cache = await caches.open(CACHE);
  try {
    // Fetch and verify the complete shell before making this worker active.
    const responses = await Promise.all(RELEASE.shell.map(key => verifiedFetch(key,
      revisionDigest(key) || RELEASE.documents[documentPath(key)])));
    await Promise.all(RELEASE.shell.map((key, index) => cache.put(key, responses[index])));
    await self.skipWaiting();
  } catch (error) {
    if (!existed) await caches.delete(CACHE);
    throw error;
  }
})()));

self.addEventListener("activate", event => event.waitUntil((async () => {
  const names = await caches.keys();
  const previous = names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE).slice(-1);
  await Promise.all(names.filter(name => (name.startsWith(CACHE_PREFIX) && name !== CACHE && !previous.includes(name))
    || name.startsWith("bhakti-shell-v")).map(name => caches.delete(name)));
  await self.clients.claim();
})()));

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin
      || request.destination === "audio" || request.destination === "video"
      || /\.(?:m4a|m4b|aac|mp4|webm|ogg|oga|opus|mp3|wav|flac|aiff?)$/i.test(url.pathname)) return;
  const owns = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  if (request.mode === "navigate") {
    if (!owns(RELEASE.documents, documentPath(url.pathname))) return;
    event.respondWith((async () => {
      try {
        // HTML is the small freshness boundary. New release documents carry new
        // resource identities even before their worker has installed.
        const response = await fetch(request, { cache: "no-cache" });
        if (!response.ok) throw new TypeError("Document unavailable");
        // Keep the accepted offline shell coherent if a newer deploy is seen
        // before its worker installs (or while that installation fails).
        if (await matchesDigest(response, RELEASE.documents[documentPath(url.pathname)])) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => {}));
        }
        return response;
      } catch (_) {
        return await (await caches.open(CACHE)).match(request)
          || await (await caches.open(CACHE)).match(url.pathname)
          || await (await caches.open(CACHE)).match("/") || Response.error();
      }
    })());
    return;
  }
  if (!owns(RELEASE.paths, url.pathname)) return;
  // Unknown queries remain distinct and are never admitted into the public cache.
  // Explicit old content hashes can still resolve in the retained prior cache.
  if (url.search && !/^\?v=[a-f0-9]{64}$/.test(url.search)) return;
  const key = url.search ? url.pathname + url.search : RELEASE.paths[url.pathname];
  const digest = revisionDigest(key);
  event.respondWith((async () => {
    const hit = await cachedRevision(key).catch(() => undefined);
    if (hit) return hit;
    const response = await verifiedFetch(key, digest);
    // Resources from a newer HTML release are kept under their exact identity;
    // the current worker never aliases them to its own version.
    const copy = response.clone();
    // Storage pressure must never turn a successful network fetch into a broken
    // reader. Persist in the event lifetime without delaying resource delivery.
    event.waitUntil(caches.open(CACHE).then(cache => cache.put(key, copy)).catch(() => {}));
    return response;
  })());
});
