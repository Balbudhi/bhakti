#!/usr/bin/env node
"use strict";

// Run the production update policy with controlled lifecycle events. This
// verifies reload decisions, not Safari's installed-app/process behavior.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require.resolve("../assets/pwa.js"), "utf8");

async function setup({ controlled = true, paused = true, currentTime = 0, pending = false } = {}) {
  const callbacks = new Map();
  const listen = prefix => (type, callback) => {
    const key = prefix + type;
    callbacks.set(key, [...(callbacks.get(key) || []), callback]);
  };
  const emit = async (prefix, type, event = {}) => {
    for (const callback of callbacks.get(prefix + type) || []) await callback(event);
  };
  let reloads = 0;
  const audio = { paused, currentTime, ended: false, addEventListener: listen("audio:") };
  const playback = { isPending: () => pending };
  const document = { visibilityState: "visible", querySelector: () => audio,
    addEventListener: listen("document:") };
  const window = { addEventListener: listen("window:"), location: { reload: () => reloads++ },
    BHAKTI_READER: { playback: () => playback } };
  const serviceWorker = { controller: controlled ? {} : null,
    addEventListener: listen("worker:"), register: async () => ({ update: async () => {} }) };
  vm.runInNewContext(source, { window, document, navigator: { serviceWorker }, Date });
  await emit("window:", "load");
  return { audio, document, emit, reloads: () => reloads,
    setPending: value => { pending = value; } };
}

(async () => {
  const active = await setup({ paused: false, currentTime: 42 });
  await active.emit("worker:", "controllerchange");
  assert.equal(active.reloads(), 0, "An update cannot interrupt playing audio");
  active.audio.paused = true;
  await active.emit("audio:", "pause");
  assert.equal(active.reloads(), 0, "Pausing must preserve listening position after an update");
  active.document.visibilityState = "hidden";
  await active.emit("document:", "visibilitychange");
  active.document.visibilityState = "visible";
  await active.emit("document:", "visibilitychange");
  assert.equal(active.reloads(), 0, "Returning to a paused session must not reload it");

  const requested = await setup();
  requested.setPending(true);
  await requested.emit("audio:", "bhakti:playback-state");
  await requested.emit("worker:", "controllerchange");
  assert.equal(requested.reloads(), 0, "Pending playback must survive an update");
  requested.setPending(false);
  await requested.emit("audio:", "bhakti:playback-state");
  await requested.emit("document:", "visibilitychange");
  assert.equal(requested.reloads(), 0, "Canceling playback must not enable a surprise reload");

  const fromStart = await setup();
  fromStart.audio.paused = false;
  await fromStart.emit("audio:", "play");
  fromStart.audio.paused = true;
  fromStart.audio.ended = true;
  await fromStart.emit("worker:", "controllerchange");
  assert.equal(fromStart.reloads(), 0, "A completed session remains intact for replay");

  const paused = await setup({ currentTime: 42 });
  await paused.emit("worker:", "controllerchange");
  assert.equal(paused.reloads(), 0, "Previously paused audio is protected at script startup");

  const idle = await setup();
  await idle.emit("worker:", "controllerchange");
  await idle.emit("worker:", "controllerchange");
  assert.equal(idle.reloads(), 1, "Unused documents still adopt updates once");

  const hidden = await setup();
  hidden.document.visibilityState = "hidden";
  await hidden.emit("worker:", "controllerchange");
  assert.equal(hidden.reloads(), 0, "Hidden idle documents wait for foreground");
  hidden.document.visibilityState = "visible";
  await hidden.emit("document:", "visibilitychange");
  assert.equal(hidden.reloads(), 1);

  const install = await setup({ controlled: false });
  await install.emit("worker:", "controllerchange");
  assert.equal(install.reloads(), 0, "First service-worker installation never reloads");
  console.log("PWA update lifecycle policy passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
