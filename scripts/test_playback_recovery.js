#!/usr/bin/env node
"use strict";

// Production controller, deterministic clock and native-event seam. This tests
// recovery decisions, NOT iOS audio output. Frozen currentTime despite playing
// is the reported WebKit condition. Distinct cases reject unconditional reload,
// autoplay after pause, unbounded recovery and treating a seek as playback.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require("node:path").join(__dirname, "../assets/song.js"), "utf8");
const code = source.slice(source.indexOf("const PLAYBACK_CONTROLLERS"), source.indexOf("function fmtTime"));
function events(target = {}) {
  const listeners = new Map();
  return Object.assign(target, {
    addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); },
    dispatchEvent(event) { for (const fn of listeners.get(event.type) || []) fn(event); return !event.defaultPrevented; },
    emit(type) { this.dispatchEvent({ type, target: this }); },
  });
}
function setup({ unsupported = false, throws = false } = {}) {
  let now = 0, id = 0;
  const timers = new Map(), requests = [], problems = [];
  const session = events({ state: "active", type: "auto" });
  if (throws) Object.defineProperty(session, "type", { get: () => "auto", set() { throw Error("unsupported"); } });
  const win = events({ navigator: unsupported ? {} : { audioSession: session },
    performance: { now: () => now },
    setTimeout(fn, delay) { timers.set(++id, { fn, due: now + delay }); return id; },
    clearTimeout(key) { timers.delete(key); },
  });
  const doc = events({ visibilityState: "visible", defaultView: win });
  const audio = events({ ownerDocument: doc, paused: true, ended: false, seeking: false,
    readyState: 4, networkState: 1, currentTime: 42, duration: 240, error: null, loads: 0,
    querySelectorAll: () => [{}],
    play() { this.paused = false; this.emit("play"); return new Promise((resolve, reject) => requests.push({ resolve, reject })); },
    pause() { this.paused = true; this.emit("pause"); },
    load() { this.loads++; this.readyState = 0; this.currentTime = 0; this.error = null; },
  });
  audio.addEventListener("bhakti:playback-problem", e => { problems.push(e.detail); e.preventDefault(); });
  const ctx = vm.createContext({ CustomEvent, Promise, showControlStatus() {} });
  vm.runInContext(code, ctx);
  const playback = ctx.getPlaybackController(audio);
  const tick = ms => {
    const end = now + ms;
    while (true) {
      const next = [...timers].sort((a, b) => a[1].due - b[1].due)[0];
      if (!next || next[1].due > end) break;
      now = next[1].due; timers.delete(next[0]); next[1].fn();
    }
    now = end;
  };
  const start = () => { playback.play(); audio.emit("playing"); };
  const visible = value => { doc.visibilityState = value ? "visible" : "hidden"; doc.emit("visibilitychange"); };
  return { audio, playback, requests, problems, timers, session, win, start, tick, visible };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  let app = setup();
  assert.equal(app.session.type, "playback", "Music declares a playback audio session before starting");
  for (const options of [{ unsupported: true }, { throws: true }]) {
    const other = setup(options); other.start(); assert.equal(other.requests.length, 1); other.playback.pause();
  }
  app.start();
  for (let i = 0; i < 6; i++) { app.audio.currentTime++; app.tick(4000); }
  assert.equal(app.requests.length, 1, "Healthy playback must not be restarted");
  assert.equal(app.audio.loads, 0);
  assert.equal(app.timers.size, 1, "Only one monitor may be live");
  app.visible(false); app.tick(60000);
  assert.equal(app.requests.length, 1, "No background recovery or polling");
  assert.equal(app.timers.size, 0);
  app.visible(true); app.win.emit("pageshow");
  assert.equal(app.timers.size, 1, "Restoration events must coalesce");
  app.tick(4000);
  assert.equal(app.requests.length, 2, "Frozen playback gets one restart");
  assert.equal(app.audio.currentTime, 48, "Recovery retains the exact position");
  assert.equal(app.audio.loads, 0, "First recovery retains native buffered media");
  app.requests[1].resolve(); await flush();
  app.tick(4000);
  assert.equal(app.audio.paused, true, "A second frozen interval becomes actionable Play");
  assert.equal(app.playback.isPending(), false);
  assert.equal(app.playback.isPlaying(), false);
  assert.equal(app.problems.length, 1);
  assert.equal(app.problems[0].advance, false, "Interruption must not skip the song");
  app.tick(60000); assert.equal(app.requests.length, 2, "Recovery is bounded");
  app.playback.play(null, { retry: true });
  assert.equal(app.audio.loads, 1, "Explicit retry reinitializes a still-frozen resource");
  app.audio.readyState = 1; app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 48);
  app.playback.pause(); app.requests[2].resolve(); await flush();
  app.tick(60000); assert.equal(app.requests.length, 3, "Pause cancels recovery");

  app = setup(); app.start(); app.playback.reset(); app.tick(60000);
  assert.equal(app.requests.length, 1, "Replacement cancels old recovery");
  app = setup(); app.start(); app.audio.pause(); app.visible(false); app.visible(true); app.tick(60000);
  assert.equal(app.requests.length, 1, "An OS pause is not permission to resume");
  // Browser/native resume can occur without routing through controller.play().
  app.audio.play(); app.audio.emit("playing");
  assert.equal(app.playback.isPlaying(), true, "Native resume must refresh shared controls");
  app.playback.pause();

  app = setup(); app.start(); app.tick(4000);
  app.audio.emit("pause"); // Native pause from recovery arrives after play().
  app.requests[1].resolve(); await flush();
  assert.equal(app.playback.isPlaying(), true, "Queued pause cannot cancel recovery");
  app.audio.currentTime++; app.tick(4000);
  app.tick(4000);
  assert.equal(app.requests.length, 3, "Real progress permits recovery of a later freeze");
  app.playback.pause();
  app = setup(); app.start(); app.tick(4000);
  app.requests[1].reject({ name: "NotAllowedError" }); await flush();
  assert.equal(app.audio.paused, true);
  assert.equal(app.playback.isPending(), false);
  assert.equal(app.problems[0].advance, false, "Blocked recovery must not advance the queue");
  app.tick(60000); assert.equal(app.requests.length, 2);

  app = setup(); app.start(); app.tick(8000);
  app.playback.play(73, { retry: true }); // Reload has not produced metadata.
  assert.equal(app.audio.currentTime, 0);
  app.tick(16000);
  assert.equal(app.audio.paused, true);
  app.playback.play(null, { retry: true });
  app.audio.readyState = 1; app.audio.emit("loadedmetadata");
  assert.equal(app.audio.currentTime, 73, "Timeout must retain a pending lyric seek across retries");
  app.playback.pause();

  app = setup(); app.start(); app.audio.readyState = 2; app.audio.emit("waiting");
  app.tick(4000); assert.equal(app.requests.length, 1, "Buffering is not a frozen decoder");
  app.tick(12000); assert.equal(app.playback.isPending(), false, "Loading cannot strand Cancel loading forever");
  assert.equal(app.audio.paused, true); assert.equal(app.problems[0].advance, false);
  app = setup(); app.start(); app.audio.seeking = true; app.tick(4000);
  assert.equal(app.requests.length, 1, "Do not restart a legitimate seek");
  app.tick(12000); assert.equal(app.audio.paused, true, "A stuck seek also has a bounded wait");
  app = setup(); app.start(); app.session.state = "interrupted"; app.session.emit("statechange"); app.tick(60000);
  assert.equal(app.requests.length, 1, "Do not compete for audio focus during an interruption");
  app.session.state = "active"; app.session.emit("statechange"); app.audio.currentTime++; app.tick(4000);
  assert.equal(app.requests.length, 1, "A healthy native resume needs no recovery");
  app.playback.pause();
  console.log("Playback recovery: session setup, frozen/healthy/loading/seek states, lifecycle, native resume and cancellation passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
