#!/usr/bin/env -S deno run --allow-read --allow-net=127.0.0.1
// Real CacheStorage and HTTP responses, production worker event handlers.
// This verifies offline keys, not installed Safari process behavior.
import assert from "node:assert/strict";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const source = await Deno.readTextFile(new URL("sw.js", root));
const index = await Deno.readTextFile(new URL("index.html", root));
const cacheNames = new Set();
const prefix = `bhakti-cache-test-${crypto.randomUUID()}-`;
const server = Deno.serve({ hostname: "127.0.0.1", port: 0, onListen() {} }, async request => {
  const path = new URL(request.url).pathname;
  try {
    const body = await Deno.readFile(new URL(path === "/" ? "index.html" : path.slice(1), root));
    return new Response(body);
  } catch { return new Response("Missing", { status: 404 }); }
});
const origin = `http://127.0.0.1:${server.addr.port}`;
const absolute = request => typeof request === "string" ? new URL(request, origin).href : request;
let offline = false;
const handlers = new Map();
const cacheStorage = {
  async open(name) {
    cacheNames.add(name);
    const cache = await caches.open(prefix + name);
    return {
      // Deno exposes native put/match but not addAll. Seed the real cache with
      // the production precache list and actual HTTP bodies; key matching stays native.
      addAll: async requests => {
        const responses = await Promise.all(requests.map(request => fetch(absolute(request))));
        assert.ok(responses.every(response => response.ok), "Every precache resource must exist");
        await Promise.all(requests.map((request, i) => cache.put(absolute(request), responses[i])));
      },
      put: (request, response) => cache.put(absolute(request), response),
      match: (request, options) => cache.match(absolute(request), options),
    };
  },
  async match(request, options) {
    for (const name of cacheNames) {
      const cache = await caches.open(prefix + name);
      const found = await cache.match(absolute(request), options);
      if (found) return found;
    }
  },
  keys: async () => [...cacheNames],
  delete: name => { cacheNames.delete(name); return caches.delete(prefix + name); },
};
vm.runInNewContext(source, {
  self: { location: { origin }, addEventListener: (name, callback) => handlers.set(name, callback),
    skipWaiting() {}, clients: { claim() {} } },
  caches: cacheStorage, URL, Response,
  fetch: (request, options) => offline ? Promise.reject(new TypeError("Offline")) : fetch(request, options),
});
async function lifecycle(name) {
  const tasks = [];
  handlers.get(name)({ waitUntil: promise => tasks.push(promise) });
  await Promise.all(tasks);
}
async function request(url, { navigation = false, ...options } = {}) {
  const pending = [];
  let response;
  // The browser supplies navigate mode; script-created Request disallows it.
  const native = navigation ? { url: new URL(url, origin).href, method: "GET", mode: "navigate" }
    : new Request(new URL(url, origin), options);
  handlers.get("fetch")({ request: native, respondWith: promise => { response = promise; },
    waitUntil: promise => pending.push(promise) });
  const result = await response;
  await Promise.all(pending);
  return result;
}

try {
  await lifecycle("install");
  await lifecycle("activate");
  offline = true; // No controlled online fetch has populated versioned URLs.
  const manifest = JSON.parse(await Deno.readTextFile(new URL("manifest.webmanifest", root)));
  const offlineIndex = await (await request(manifest.start_url, { navigation: true })).text();
  assert.equal(offlineIndex, index, "Installed launch returns the precached library shell");
  const bootstrap = [...offlineIndex.matchAll(/(?:src|href)="(\/(?:assets\/[^"#]+|data\/songs\.js[^"#]*|manifest\.webmanifest[^"#]*))"/g)]
    .map(match => match[1]);
  assert.ok(bootstrap.some(url => url.includes("?v=")), "Exercise the deployed versioned shell");
  for (const url of bootstrap) {
    const response = await request(url);
    assert.ok(response?.ok, `First-install offline cache miss: ${url}`);
    const expectedPath = new URL(url, origin).pathname.slice(1);
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), await Deno.readFile(new URL(expectedPath, root)), url);
  }
  for (const url of ["/assets/media-session.js", "/assets/owner-entry.js", "/assets/player-icons.svg"]) {
    assert.ok((await request(url))?.ok, `Deferred bootstrap missing: ${url}`);
  }
  assert.equal(await request("https://other.example/assets/song.js?v=1"), undefined,
    "A foreign origin must not receive the local shell");
  const cache = await cacheStorage.open([...cacheNames][0]);
  await cache.put("/songs/test/data.js?edition=one", new Response("edition one"));
  assert.equal(await request("/songs/test/data.js?edition=two"), undefined,
    "Do not discard query parameters outside the explicit shell");
  assert.equal(await (await request("/songs/test/data.js?edition=one")).text(), "edition one");
  assert.equal(await request("/songs/test/audio.m4a"), undefined, "Audio remains outside worker handling");
  assert.equal(await request("/assets/song.js", { method: "POST" }), undefined);
  offline = false;
  assert.ok((await request("/assets/song.js?v=new-release"))?.ok);
  offline = true;
  assert.ok((await request("/assets/song.js?v=new-release"))?.ok);
  console.log(`PASS: ${bootstrap.length} actual index asset URLs load offline immediately after install; query/origin isolation retained`);
} finally {
  await server.shutdown();
  for (const name of cacheNames) await caches.delete(prefix + name);
}
