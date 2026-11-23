#!/usr/bin/env node
"use strict";
// Runs the shipped counter with real Request semantics left to the browser boundary.
// Partitions: first/returning/already counted/day rolled over; hidden then visible;
// lost answer, second window, not counted; rejected, malformed and offline answers; corrupt, absent and refused storage;
// other host; automation; overlapping events.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../assets/visit.js"), "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));

async function fixture({ stored, host = "bhakti.eeshan.xyz", webdriver = false, visible = true, now = 1000, answer, storage } = {}) {
  const saved = new Map(stored === undefined ? [] : [["bhakti-visit", stored]]);
  const calls = [], handlers = {};
  const state = { now, answer: answer || (() => ({ ok: true, json: async () => ({ day: "2026-11-22", until: 5000 }) })) };
  const document = { visibilityState: visible ? "visible" : "hidden", addEventListener: (type, fn) => { handlers[type] = fn; } };
  vm.runInNewContext(source, {
    document, location: { hostname: host }, navigator: { webdriver },
    Date: class extends Date { static now() { return state.now; } },
    localStorage: storage || { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) },
    fetch: async (url, options) => { calls.push({ url, ...options }); return state.answer(); },
  });
  await settle(); await settle();
  const show = async () => { document.visibilityState = "visible"; handlers.visibilitychange?.(); await settle(); await settle(); };
  return { calls, saved, state, show, handlers, document };
}

(async () => {
  const first = await fixture();
  assert.equal(first.calls.length, 1);
  const { url, method, mode, credentials, body, headers } = first.calls[0];
  assert.deepEqual({ url, method, mode, credentials, body }, { url: "https://owner.bhakti.eeshan.xyz/api/visit", method: "POST", mode: "cors", credentials: "omit", body: "{}" });
  // A preflight would fail: only safelisted headers may be sent.
  assert.deepEqual(Object.entries(headers), [["Content-Type", "text/plain"]]);
  assert.deepEqual(JSON.parse(first.saved.get("bhakti-visit")), { day: "2026-11-22", until: 5000 });
  assert.equal(first.saved.size, 1);
  await first.show();
  assert.equal(first.calls.length, 1, "already counted today");
  first.state.now = 5000;
  await first.show();
  assert.equal(first.calls.length, 2, "an open page is counted again on a later day");
  assert.equal(first.calls[1].body, '{"last":"2026-11-22"}');

  const hidden = await fixture({ visible: false });
  assert.equal(hidden.calls.length, 0);
  await hidden.show();
  assert.equal(hidden.calls.length, 1);

  for (const answer of [() => ({ ok: false, json: async () => ({}) }), () => { throw new TypeError("offline"); }, () => ({ ok: true, json: async () => { throw new SyntaxError("html"); } })]) {
    const f = await fixture({ stored: '{"day":"2026-11-20","until":10}', answer });
    assert.equal(f.calls.length, 1);
    assert.deepEqual(JSON.parse(f.saved.get("bhakti-visit")), { day: "2026-11-20", until: 601000 }, "failure keeps the previous day");
    await f.show();
    assert.equal(f.calls.length, 1, "no retry storm");
    f.state.now = 601000;
    await f.show();
    assert.equal(f.calls.length, 2, "a later view retries");
    assert.equal(f.calls[1].body, '{"last":"2026-11-20"}');
  }
  for (const stored of ["{", "null", "[]", '{"day":"x","until":1}', '{"day":"2026-11-20"}']) {
    const f = await fixture({ stored });
    assert.equal(f.calls[0].body, "{}", stored);
    assert.equal(JSON.parse(f.saved.get("bhakti-visit")).day, "2026-11-22");
  }
  const refuse = () => { throw new Error("SecurityError"); };
  assert.equal((await fixture({ storage: { getItem: refuse, setItem: refuse } })).calls.length, 0);
  assert.equal((await fixture({ storage: { getItem: () => null, setItem: refuse } })).calls.length, 0);
  for (const host of ["localhost", "balbudhi.github.io", "owner.bhakti.eeshan.xyz"]) assert.equal((await fixture({ host })).calls.length, 0);
  assert.equal((await fixture({ webdriver: true })).calls.length, 0);

  // An unanswered request (closed page) or a second window does not send again.
  const lost = await fixture({ answer: () => new Promise(() => {}) });
  assert.equal(lost.calls.length, 1);
  assert.equal((await fixture({ stored: lost.saved.get("bhakti-visit") })).calls.length, 0);
  // A device the server did not count keeps no day and waits for the next one.
  const refused = await fixture({ answer: () => ({ ok: true, json: async () => ({ day: null, until: 5000 }) }) });
  await refused.show();
  assert.equal(refused.calls.length, 1);
  refused.state.now = 5000;
  await refused.show();
  assert.equal(refused.calls[1].body, "{}");

  let release;
  const busy = await fixture({ answer: () => new Promise(resolve => { release = resolve; }) });
  await busy.show(); await busy.show();
  assert.equal(busy.calls.length, 1, "one request at a time");
  release({ ok: true, json: async () => ({ day: "2026-11-22", until: 5000 }) });

  // Loaded by the app after initialization, precached with the shell, published.
  const read = name => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
  assert.match(read("assets/app.js"), /initializeState\(\);[\s\S]*import\(assetPath\("\/assets\/visit\.js"\)\)\.catch/);
  assert.match(read("scripts/assemble_public_site.py"), /'\/assets\/visit\.js'/);
  assert.match(read("sw.js"), /"\/assets\/visit\.js"/);
  console.log("visit counter: daily count, retry, storage and privacy cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
