#!/usr/bin/env node
"use strict";

// Exercise the production app's completion routing and playback controller
// together. Controlled media events test intent/seek/failure routing, not a
// browser's decoding, native event ordering or autoplay policy.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const Queue = require("../assets/queue.js");
const appSource = fs.readFileSync(require.resolve("../assets/app.js"), "utf8");
const readerSource = fs.readFileSync(require.resolve("../assets/song.js"), "utf8");
const a = {slug: "a", queueId: "a"};
const b = {slug: "b", queueId: "b"};

function setup(items, currentIndex, repeat, { failSelection = false } = {}) {
  const listeners = new Map();
  const audio = {
    paused: true, ended: false, readyState: 4, currentTime: 75,
    error: null, dataset: {songSlug: items[currentIndex].slug},
    sources: [{}], plays: 0,
    addEventListener(type, callback) {
      const callbacks = listeners.get(type) || [];
      callbacks.push(callback);
      listeners.set(type, callbacks);
    },
    dispatchEvent(event) {
      for (const callback of listeners.get(event.type) || []) callback(event);
      return !event.defaultPrevented;
    },
    querySelectorAll() { return this.sources; },
    play() { this.plays++; this.paused = false; this.ended = false; return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new Event("pause")); },
  };
  const state = Queue.create({mode: items.length === 1 ? "standalone" : "custom",
    items, currentIndex, repeat, sessionId: "test"});
  const selected = [], navigated = [], statuses = [];
  const context = vm.createContext({Queue, audio, CustomEvent, WeakMap, Set, Promise,
    queueState: state, currentSong: state.items[currentIndex], advancing: false,
    view: "song", showControlStatus() {}, updateQueuePlayback() {},
    queueIsVisible: state => state.mode !== "standalone",
    setQueueState(next) { context.queueState = next; context.currentSong = next.items[next.currentIndex]; },
    revealCurrentQueueRow() {}, showStatus(message) { statuses.push(message); },
    selectAudioSong(item) {
      selected.push(item.entryId);
      if (failSelection) {
        audio.sources = [];
        vm.runInContext("playback.reset(); playback.play();", context);
      }
    },
    showSong(slug) { navigated.push(slug); },
  });
  const controllerStart = readerSource.indexOf("const PLAYBACK_CONTROLLERS");
  vm.runInContext(readerSource.slice(controllerStart, readerSource.indexOf("function fmtTime", controllerStart)), context);
  vm.runInContext("const playback = getPlaybackController(audio);", context);
  const advanceStart = appSource.indexOf("  const advanceQueue =");
  vm.runInContext(appSource.slice(advanceStart, appSource.indexOf("  const initializeState", advanceStart)), context);
  const eventsStart = appSource.indexOf('  audio.addEventListener("bhakti:playback-state"');
  vm.runInContext(appSource.slice(eventsStart, appSource.indexOf('  audio.addEventListener("playing"', eventsStart)), context);
  const end = () => {
    audio.ended = true; audio.paused = true;
    audio.dispatchEvent(new Event("ended"));
  };
  return {audio, context, selected, navigated, statuses, end};
}

for (const items of [[a], [a, b]]) {
  const test = setup(items, 0, "one");
  const entry = test.context.currentSong.entryId;
  test.end();
  assert.equal(test.audio.currentTime, 0, "Natural completion seeks to the beginning");
  assert.equal(test.audio.plays, 1);
  assert.equal(test.context.currentSong.entryId, entry);
  assert.deepEqual(test.selected, [], "Repeat-one must reuse the loaded recording");
  assert.deepEqual(test.navigated, [], "Repeat-one must preserve the reading view");
}
const all = setup([a, b], 1, "all");
all.end();
assert.equal(all.context.queueState.currentIndex, 0);
assert.deepEqual(all.navigated, ["a"]);
assert.equal(all.selected.length, 1);
const soloAll = setup([a], 0, "all");
soloAll.end();
assert.equal(soloAll.audio.plays, 1);
assert.equal(soloAll.audio.currentTime, 0);
for (const items of [[a], [a, b]]) {
  const off = setup(items, items.length - 1, "off");
  off.end();
  assert.equal(off.audio.plays, 0);
  assert.deepEqual(off.selected, []);
}
const next = setup([a, b], 0, "one");
vm.runInContext("advanceQueue()", next.context);
assert.equal(next.context.queueState.currentIndex, 1);
assert.equal(next.audio.plays, 0);
for (const repeat of ["one", "all"]) {
  const failed = setup([a, b], 1, repeat);
  failed.audio.dispatchEvent(new CustomEvent("bhakti:playback-problem", {
    cancelable: true, detail: {message: "Unavailable", advance: true},
  }));
  assert.deepEqual(failed.selected, [], "Failure cannot wrap or retry the same song");
  assert.equal(failed.audio.plays, 0);
}

// An unavailable newly selected source reports failure synchronously through
// the real controller. The app's advancing guard must not swallow that event.
const cascade = setup([a, b, a], 0, "all", { failSelection: true });
vm.runInContext("advanceQueue()", cascade.context);
assert.equal(cascade.selected.length, 2, "Every later occurrence is attempted once");
assert.equal(cascade.context.queueState.currentIndex, 2);
assert.equal(cascade.statuses.at(-1), "No playable songs remain");
assert.equal(cascade.audio.plays, 0);

// Execute the actual queue renderer. These assertions check generated markup,
// not browser layout, native focus restoration or touch behavior.
function render(state) {
  const queueSheet = {
    innerHTML: "", contains: () => false,
    querySelector: () => ({scrollTop: 0}),
  };
  const context = vm.createContext({
    queueState: state, queueSheet, draggedRow: null,
    document: {activeElement: null}, updateQueuePlayback() {},
    escapeHtml: value => String(value ?? ""), playIcon: "", pauseIcon: "",
  });
  const start = appSource.indexOf("  const renderQueueSheet =");
  vm.runInContext(appSource.slice(start, appSource.indexOf("  const revealCurrentQueueRow", start)), context);
  vm.runInContext("renderQueueSheet()", context);
  return queueSheet.innerHTML;
}
const rows = Queue.create({mode: "custom", items: [a, b, a], currentIndex: 1, sessionId: "render"});
const html = render(rows);
assert.equal((html.match(/data-queue-action="remove"/g) || []).length, 2);
assert.equal((html.match(/aria-current="true"/g) || []).length, 1);
assert.doesNotMatch(html, />Current</);
for (const repeat of ["off", "one", "all"]) {
  const markup = render(Queue.create({...rows, currentIndex: 2, repeat}));
  const nextButton = markup.match(/<button[^>]*data-queue-action="next"[^>]*>/)[0];
  assert.equal(nextButton.includes(" disabled"), repeat !== "all");
}
console.log("Repeat completion and playback-controller integration passed");
