#!/usr/bin/env node
"use strict";

// Production controller logic with a controlled media-event/promise seam.
// This does not emulate native source selection; real 404 and fallback behavior
// must additionally be checked in the in-app browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../assets/song.js"), "utf8");
const start = source.indexOf("const PLAYBACK_CONTROLLERS");
assert.ok(start >= 0, "The shared playback owner must be present");
const context = vm.createContext({ WeakMap, Set, CustomEvent, Promise, showControlStatus() {} });
vm.runInContext(source.slice(start, source.indexOf("function fmtTime", start)), context);

function setup(count = 2, { readyState = 0, networkState = 2, paused = true } = {}) {
  const listeners = new Map();
  const requests = [];
  const problems = [];
  const audio = {
    paused, ended: false, readyState, networkState, currentTime: 0,
    error: null, loads: 0,
    addEventListener(type, callback, capture = false) {
      const entries = listeners.get(type) || [];
      entries.push({ callback, capture }); listeners.set(type, entries);
    },
    dispatchEvent(event) { for (const { callback } of listeners.get(event.type) || []) callback(event); return !event.defaultPrevented; },
    emit(type) { this.dispatchEvent({ type, target: this }); },
    querySelectorAll() { return this.sources; },
    play() {
      this.paused = false;
      this.emit("play");
      return new Promise((resolve, reject) => requests.push({ resolve, reject }));
    },
    pause() { this.paused = true; this.emit("pause"); },
    load() { this.loads++; this.networkState = 2; this.error = null; },
  };
  audio.sources = Array.from({ length: count }, () => ({ tagName: "SOURCE", parentElement: audio }));
  audio.addEventListener("bhakti:playback-problem", event => { problems.push(event.detail); event.preventDefault(); });
  const playback = context.getPlaybackController(audio);
  function failSource(node) {
    for (const { callback, capture } of listeners.get("error") || []) {
      if (capture) callback({ target: node });
    }
  }
  return { audio, playback, requests, problems, failSource };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  // A first source failure must leave fallback selection and playback intact.
  let app = setup();
  app.playback.play();
  assert.equal(app.requests.length, 1, "Native play starts within the user gesture");
  assert.equal(app.playback.isPlaying(), false, "Native play event is not proof of playback");
  app.failSource(app.audio.sources[0]);
  assert.equal(app.problems.length, 0);
  app.audio.readyState = 3;
  app.audio.emit("playing");
  app.requests[0].resolve();
  await flush();
  assert.equal(app.playback.isPlaying(), true);
  assert.equal(app.audio.paused, false);

  // Waiting reflects an actual buffer underrun; a stalled download or stale
  // waiting event does not claim that buffered audio has stopped playing.
  app.audio.emit("stalled");
  assert.equal(app.playback.isPlaying(), true);
  app.audio.emit("waiting");
  assert.equal(app.playback.isPlaying(), true);
  app.audio.readyState = 2;
  app.audio.emit("waiting");
  assert.equal(app.playback.isPlaying(), false);
  assert.equal(app.playback.isPending(), true);
  app.audio.readyState = 3;
  app.audio.emit("playing");
  assert.equal(app.playback.isPlaying(), true);
  assert.equal(app.playback.isPending(), false);
  app.audio.readyState = 2;
  app.audio.emit("waiting");
  app.playback.pause();
  app.audio.emit("waiting");
  assert.equal(app.playback.isPending(), false, "Pause cancels buffering intent");

  // Full exhaustion with intent pauses and may advance, exactly once.
  app = setup();
  app.playback.play(17);
  app.failSource(app.audio.sources[0]);
  app.failSource(app.audio.sources[1]);
  assert.equal(app.audio.paused, true);
  assert.equal(app.playback.isPlaying(), false);
  assert.equal(app.problems.length, 1);
  assert.equal(app.problems[0].advance, true);
  app.failSource(app.audio.sources[1]);
  assert.equal(app.problems.length, 1);
  app.audio.readyState = 1;
  app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 0, "A failed request must not leave a seek behind");
  app.requests[0].resolve();
  await flush();
  assert.equal(app.playback.isPlaying(), false);

  // Idle preload failure does not autoplay. A later explicit request may skip it
  // without entering the native play() promise that never settles for <source>.
  app = setup(1);
  app.failSource(app.audio.sources[0]);
  assert.equal(app.problems[0].advance, false);
  app.playback.play();
  assert.equal(app.requests.length, 0);
  assert.equal(app.problems[1].advance, true);
  assert.equal(app.audio.paused, true);

  // If source errors preceded binding, reselect once with listeners installed.
  app = setup(1, { networkState: 3 });
  assert.equal(app.audio.loads, 1);
  app.playback.play();
  assert.equal(app.audio.loads, 1);
  assert.equal(app.requests.length, 1);
  app.failSource(app.audio.sources[0]);
  assert.equal(app.problems[0].advance, true);

  app = setup(1, { readyState: 1 });
  assert.equal(app.audio.loads, 0, "Loaded metadata must not be discarded");
  app = setup(1, { readyState: 3, paused: false });
  assert.equal(app.audio.loads, 0, "Playing media must not be restarted");

  // Queued events from load/pause must not cancel the newest playback request.
  app = setup(1);
  app.playback.play(18);
  app.audio.emit("pause"); // Old queued event; newest play has paused=false.
  app.audio.emit("emptied");
  app.audio.emit("error"); // No current MediaError; event belongs to old resource.
  app.audio.readyState = 1;
  app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 18);
  app.requests[0].resolve();
  await flush();
  assert.equal(app.playback.isPlaying(), true);
  assert.equal(app.problems.length, 0);

  // Replacements invalidate pending promises, stale source nodes and seeks.
  app = setup(1);
  app.playback.play(22);
  const removed = app.audio.sources[0];
  app.playback.reset();
  removed.parentElement = null;
  app.audio.sources = [{ tagName: "SOURCE", parentElement: app.audio }];
  app.failSource(removed);
  app.requests[0].resolve();
  app.audio.readyState = 1;
  app.audio.emit("loadedmetadata");
  await flush();
  assert.equal(app.problems.length, 0);
  assert.equal(app.playback.isPlaying(), false);
  assert.equal(app.audio.currentTime, 0);
  app.playback.play();
  assert.equal(app.requests.length, 2);

  // Latest line seek wins; pause cancels both seek and pending fulfillment.
  app = setup(1);
  app.playback.play(10);
  app.playback.play(30);
  app.audio.readyState = 1;
  app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 30);
  app.playback.pause();
  app.requests[1].resolve();
  await flush();
  assert.equal(app.playback.isPlaying(), false);
  app.audio.readyState = 0;
  app.playback.play(45);
  app.playback.pause();
  app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 30);

  // Autoplay-policy rejection reports a retry instruction, never skips a song.
  app = setup(1);
  app.playback.play();
  app.requests[0].reject({ name: "NotAllowedError" });
  await flush();
  assert.equal(app.audio.paused, true);
  assert.equal(app.problems[0].advance, false);
  assert.equal(app.playback.isPlaying(), false);
  app.playback.play();
  assert.equal(app.requests.length, 2, "A policy rejection is not terminal source failure");

  // Terminal native media errors obey the same idle/active intent boundary.
  app = setup(1);
  app.audio.error = { code: 3 };
  app.audio.emit("error");
  assert.equal(app.problems[0].advance, false);
  app.playback.play();
  assert.equal(app.problems[1].advance, true);
  assert.equal(app.requests.length, 0);

  // Automatic attempts remain terminal, but a fresh user request can retry a
  // recording after connectivity returns without first selecting another song.
  app.audio.currentTime = 42;
  app.playback.play(null, { retry: true });
  assert.equal(app.audio.loads, 2, "One initial preload and one explicit reload");
  assert.equal(app.requests.length, 1);
  app.audio.currentTime = 0;
  app.audio.readyState = 1;
  app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 42, "Explicit retry preserves position");
  assert.equal(app.playback.isPlaying(), false);
  app.audio.readyState = 3;
  app.audio.emit("playing");
  app.requests[0].resolve();
  await flush();
  assert.equal(app.playback.isPlaying(), true);
  app.audio.error = { code: 2 };
  app.audio.emit("error");
  app.playback.play();
  assert.equal(app.audio.loads, 2, "Automatic failure handling cannot reload endlessly");
  app.audio.readyState = 0;
  app.playback.play(12, { retry: true });
  assert.equal(app.audio.loads, 3, "A second user request permits exactly one more retry");
  app.audio.readyState = 1;
  app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 12, "A requested lyric seek overrides the saved position");
  app.playback.pause();
  app.requests[1].resolve();
  await flush();
  assert.equal(app.playback.isPlaying(), false, "Pause cancels an in-flight retry");

  app = setup(0);
  app.playback.play(null, { retry: true });
  assert.equal(app.audio.loads, 0, "Absent sources cannot be reloaded into existence");
  assert.equal(app.requests.length, 0);
  console.log("Playback controller failure, fallback, intent and cancellation cases passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
