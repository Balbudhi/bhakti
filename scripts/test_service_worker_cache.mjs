#!/usr/bin/env -S deno run --allow-read --allow-net=127.0.0.1
// Assemble _site first. Native CacheStorage matching and real HTTP bodies test
// warm/cold, offline, deployment races, failures and public-cache boundaries.
// This does not claim installed Safari lifecycle or physical-device frame times.
import assert from "node:assert/strict";
import vm from "node:vm";
const root = new URL("../_site/", import.meta.url);
const source = await Deno.readTextFile(new URL("sw.js", root));
const workerSource = source.slice(source.indexOf(";\n") + 2);
const config = JSON.parse(source.slice(source.indexOf(" = ") + 3, source.indexOf(";\n")));
const index = await Deno.readTextFile(new URL("index.html", root));
const prefix = `bhakti-cache-test-${crypto.randomUUID()}-`;
const cacheNames = new Set();
const overrides = new Map();
const network = [];
let offline = false;
let refuseWrites = false;
let refuseReads = false;
const server = Deno.serve({ hostname: "127.0.0.1", port: 0, onListen() {} }, async request => {
  const path = new URL(request.url).pathname;
  if (overrides.has(path)) return new Response(overrides.get(path));
  try { return new Response(await Deno.readFile(new URL(path === "/" ? "index.html" : path.slice(1), root))); }
  catch { return new Response("Missing", { status: 404 }); }
});
const origin = `http://127.0.0.1:${server.addr.port}`;
const absolute = value => new URL(typeof value === "string" ? value : value.url, origin).href;
const cacheStorage = {
  async open(name) {
    cacheNames.add(name);
    const cache = await caches.open(prefix + name);
    return {
      put: (request, response) => refuseWrites ? Promise.reject(new DOMException("Storage full", "QuotaExceededError")) : cache.put(absolute(request), response),
      match: (request, options) => refuseReads ? Promise.reject(new Error("Cache unavailable")) : cache.match(absolute(request), options),
    };
  },
  keys: async () => [...cacheNames],
  delete: name => { cacheNames.delete(name); return caches.delete(prefix + name); },
};
function worker(configuration) {
  const handlers = new Map();
  let skipped = false;
  vm.runInNewContext('const BHAKTI_RELEASE = ' + JSON.stringify(configuration) + ';\n' + workerSource, {
    self: { location: { origin }, addEventListener: (name, callback) => handlers.set(name, callback),
      skipWaiting() { skipped = true; }, clients: { claim() {} } },
    caches: cacheStorage, URL, Response, crypto,
    fetch: (request, options) => {
      network.push(absolute(request));
      return offline ? Promise.reject(new TypeError("Offline")) : fetch(absolute(request), options);
    },
  });
  return {
    get skipped() { return skipped; },
    async lifecycle(name) {
      const pending = [];
      handlers.get(name)({ waitUntil: promise => pending.push(promise) });
      await Promise.all(pending);
    },
    async request(url, { navigation = false, method = "GET" } = {}) {
      let response;
      const pending = [];
      const request = navigation ? { url: new URL(url, origin).href, method, mode: "navigate" }
        : new Request(new URL(url, origin), { method });
      handlers.get("fetch")({ request, respondWith: promise => { response = promise; },
        waitUntil: promise => pending.push(promise) });
      const result = await response;
      await Promise.all(pending);
      return result;
    },
  };
}
const hash = async text => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))]
  .map(byte => byte.toString(16).padStart(2, "0")).join("");
try {
  const first = worker(config);
  await first.lifecycle("install"); await first.lifecycle("activate");
  assert.ok(first.skipped);
  for (const lazy of ["/assets/shuffle.js", "/assets/shuffle-worker.js", "/data/shuffle-profiles.js"])
    assert.ok(!network.some(url => new URL(url).pathname === lazy), `Startup must not download ${lazy}`);
  offline = true;
  const manifest = JSON.parse(await Deno.readTextFile(new URL("manifest.webmanifest", root)));
  assert.equal(await (await first.request(manifest.start_url, { navigation: true })).text(), index);
  const bootstrap = [...index.matchAll(/(?:src|href)="(\/(?:assets\/[^"#]+|data\/songs\.js[^"#]*|manifest\.webmanifest[^"#]*))"/g)].map(match => match[1]);
  assert.ok(bootstrap.some(url => /\?v=[a-f0-9]{64}$/.test(url)));
  for (const url of bootstrap) {
    const response = await first.request(url);
    assert.ok(response?.ok, `First-install offline miss: ${url}`);
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), await Deno.readFile(new URL(new URL(url, origin).pathname.slice(1), root)));
  }
  // Deferred bare-path icons are routed to the current revision, not refetched.
  for (const path of ["/assets/media-session.js", "/assets/owner-entry.js", "/assets/player-icons.svg"])
    assert.ok((await first.request(path))?.ok);
  offline = false; network.length = 0;
  for (const url of bootstrap) assert.ok((await first.request(url))?.ok);
  assert.equal(network.length, 0, "Warm online shell reads must make zero network requests");
  refuseReads = true;
  assert.ok((await first.request(config.paths['/assets/app.js']))?.ok,
    'A cache read failure must fall through to verified network content');
  refuseReads = false;
  for (const url of ["https://other.example/assets/song.js", "/data/editorial_baselines.json",
    "/songs/test/audio.m4a", "/assets/song.js?edition=one", "/assets/song.js?v=old&extra=1"])
    assert.equal(await first.request(url), undefined, `Excluded request: ${url}`);
  assert.equal(await first.request("/assets/song.js", { method: "POST" }), undefined);
  assert.equal(await first.request("/private/report", { navigation: true }), undefined);

  // A public lazy song resource is verified once and remains available offline.
  const song = Object.keys(config.paths).find(path => path.startsWith("/songs/") && path.endsWith("/data.js"));
  assert.ok(song);
  assert.ok((await first.request(config.paths[song]))?.ok);
  offline = true; assert.ok((await first.request(config.paths[song]))?.ok); offline = false;
  // Browser storage quota failures cannot discard an available network body.
  const uncachedSong = Object.keys(config.paths).find(path => path.startsWith('/songs/') && path.endsWith('/data.js') && path !== song);
  assert.ok(uncachedSong);
  refuseWrites = true;
  assert.ok((await first.request(config.paths[uncachedSong]))?.ok);
  assert.equal(await (await first.request('/', { navigation: true })).text(), index);
  refuseWrites = false;
  const falseRevision = '/assets/app.js?v=' + '0'.repeat(64);
  await assert.rejects(first.request(falseRevision), /revision changed/);
  offline = true; await assert.rejects(first.request(falseRevision), /Offline/); offline = false;

  // A newer HTML document may arrive before its worker. Return it online, keep
  // the coherent previous offline document, and preserve the listener's assets.
  const next = structuredClone(config);
  next.release += "-next";
  const oldApp = config.paths['/assets/app.js'];
  const appBody = '// changed release\n' + await Deno.readTextFile(new URL('assets/app.js', root));
  const newApp = '/assets/app.js?v=' + await hash(appBody);
  next.paths['/assets/app.js'] = newApp;
  next.shell = next.shell.map(key => key === oldApp ? newApp : key);
  const nextIndex = index.replaceAll(oldApp, newApp);
  next.documents['/index.html'] = await hash(nextIndex);
  overrides.set('/assets/app.js', appBody); overrides.set('/', nextIndex); overrides.set('/index.html', nextIndex);
  assert.equal(await (await first.request('/', { navigation: true })).text(), nextIndex);
  offline = true;
  assert.equal(await (await first.request('/', { navigation: true })).text(), index);
  assert.equal(await (await first.request(oldApp)).text(), await Deno.readTextFile(new URL('assets/app.js', root)));
  offline = false;
  const second = worker(next);
  await second.lifecycle('install'); await second.lifecycle('activate');
  network.length = 0;
  assert.equal(await (await second.request(newApp)).text(), appBody);
  assert.equal(await (await second.request(oldApp)).text(), await Deno.readTextFile(new URL('assets/app.js', root)));
  assert.equal(network.length, 0, 'New and retained prior revisions both stay warm');
  assert.equal([...cacheNames].filter(name => name.startsWith('bhakti-release-')).length, 2);

  // Corrupt/incomplete installs cannot activate or remove the accepted release.
  const broken = structuredClone(next); broken.release += '-broken';
  overrides.set('/assets/app.js', 'unexpected changed bytes');
  const failing = worker(broken);
  await assert.rejects(failing.lifecycle('install'), /revision changed/);
  assert.equal(failing.skipped, false);
  assert.ok(!cacheNames.has('bhakti-release-' + broken.release));
  assert.equal(await (await second.request(newApp)).text(), appBody);
  overrides.set('/assets/app.js', appBody);
  // Rotation bounds retained app caches and never deletes another app's cache.
  await cacheStorage.open('unrelated-application');
  const thirdConfig = structuredClone(next); thirdConfig.release += '-third';
  const third = worker(thirdConfig);
  await third.lifecycle('install'); await third.lifecycle('activate');
  assert.ok(!cacheNames.has('bhakti-release-' + config.release));
  assert.ok(cacheNames.has('unrelated-application'));
  assert.equal([...cacheNames].filter(name => name.startsWith('bhakti-release-')).length, 2);
  console.log(`PASS: ${bootstrap.length} assembled entrypoint resources; zero-network warm hits; native cache offline/update/integrity/isolation/rotation checks`);
} finally {
  await server.shutdown();
  for (const name of cacheNames) await caches.delete(prefix + name);
}
