#!/usr/bin/env node
"use strict";

// Test the production Media Session adapter at its browser API boundary. These
// tests establish action/state wiring, not which controls iOS chooses to show.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const source = fs.readFileSync(path.join(__dirname, "../assets/media-session.js"), "utf8");
  const { attach } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const originalMetadata = globalThis.MediaMetadata;
  const setNavigator = value => Object.defineProperty(globalThis, "navigator", { configurable: true, value });
  globalThis.MediaMetadata = class { constructor(value) { Object.assign(this, value); } };

  function setup({ unsupported = [], sessionMissing = false, positionMissing = false } = {}) {
    const audio = new EventTarget();
    Object.assign(audio, { readyState: 1, duration: 90, currentTime: 25, playbackRate: 1, paused: true, ended: false });
    const calls = { play: 0, playArgs: [], pause: 0, previous: 0, next: 0, fastSeek: [] };
    let playing = false;
    let song = { slug: "first", title: "First title", credit: "Known singer" };
    let hasPrevious = false;
    let hasNext = true;
    const emit = name => audio.dispatchEvent(new Event(name));
    audio.fastSeek = time => { calls.fastSeek.push(time); audio.currentTime = time; };
    const playback = {
      play(...args) { calls.play++; calls.playArgs.push(args); audio.paused = false; emit("bhakti:playback-state"); },
      pause() { calls.pause++; audio.paused = true; playing = false; emit("bhakti:playback-state"); },
      isPlaying: () => playing && !audio.paused && !audio.ended,
    };
    const handlers = {};
    const positions = [];
    const session = {
      metadata: null, playbackState: "none",
      setActionHandler(action, handler) {
        if (unsupported.includes(action)) throw new DOMException("Unsupported", "NotSupportedError");
        handlers[action] = handler;
      },
      setPositionState(value) { positions.push(value); },
    };
    if (positionMissing) delete session.setPositionState;
    setNavigator(sessionMissing ? {} : { mediaSession: session });
    const controller = attach({ audio, playback, getSong: () => song,
      canPrevious: () => hasPrevious, canNext: () => hasNext,
      previous: () => { calls.previous++; }, next: () => { calls.next++; } });
    return { audio, calls, emit, session, handlers, positions, controller,
      setSong(value) { song = value; controller.refresh(); },
      setQueue(previous, next) { hasPrevious = previous; hasNext = next; controller.refresh(); },
      playing() { playing = true; audio.paused = false; emit("playing"); },
    };
  }

  try {
    // Missing/partial platform support must not disable playback or other actions.
    let app = setup({ sessionMissing: true });
    app.controller.refresh();
    app.controller.destroy();
    app = setup({ unsupported: ["stop", "seekto"], positionMissing: true });
    app.handlers.play();
    assert.equal(app.calls.play, 1);
    assert.deepEqual(app.calls.playArgs[0], [null, { retry: true }], "A user media-key play can retry a failed recording");
    assert.equal(app.handlers.seekforward, null);
    assert.equal(app.handlers.seekbackward, null);
    app.controller.destroy();

    // Metadata uses evidenced credit; source/queue updates replace prior title.
    app = setup();
    assert.equal(app.session.metadata.title, "First title");
    assert.equal(app.session.metadata.artist, "Known singer");
    app.setSong({ slug: "second", title: "Second title", credit: "" });
    assert.equal(app.session.metadata.title, "Second title");
    assert.equal(app.session.metadata.artist, "");

    // A play request is pending until the controller reports actual playback.
    app.handlers.play();
    assert.equal(app.session.playbackState, "paused");
    app.playing();
    assert.equal(app.session.playbackState, "playing");
    app.handlers.pause();
    assert.equal(app.session.playbackState, "paused");
    assert.equal(app.calls.pause, 1);
    assert.deepEqual(app.positions.at(-1), { duration: 90, position: 25, playbackRate: 1 });

    // Track availability follows current queue and stale handlers recheck bounds.
    assert.equal(app.handlers.previoustrack, null);
    app.handlers.nexttrack();
    assert.equal(app.calls.next, 1);
    const oldNext = app.handlers.nexttrack;
    app.setQueue(true, false);
    assert.equal(app.handlers.nexttrack, null);
    oldNext();
    assert.equal(app.calls.next, 1);
    app.handlers.previoustrack();
    assert.equal(app.calls.previous, 1);

    // Track actions must not compete with interval-seek commands on iOS.
    // This policy applies at first/last boundaries, single songs and queue changes.
    for (const [previous, next] of [[false, true], [true, true], [true, false], [false, false]]) {
      app.setQueue(previous, next);
      assert.equal(typeof app.handlers.previoustrack === "function", previous);
      assert.equal(typeof app.handlers.nexttrack === "function", next);
      assert.equal(app.handlers.seekbackward, null);
      assert.equal(app.handlers.seekforward, null);
      assert.equal(typeof app.handlers.seekto, "function", "Scrubbing remains available");
    }

    // Scrubbing while paused never starts playback and clamps recording bounds.
    app.handlers.seekto({ seekTime: 200 });
    assert.equal(app.audio.currentTime, 90);
    app.handlers.seekto({ seekTime: -20 });
    assert.equal(app.audio.currentTime, 0);
    app.handlers.seekto({ seekTime: NaN });
    assert.equal(app.audio.currentTime, 0);
    app.handlers.seekto({ seekTime: 40, fastSeek: true });
    assert.deepEqual(app.calls.fastSeek, [40]);
    app.handlers.seekto({ seekTime: 41, fastSeek: false });
    assert.equal(app.audio.currentTime, 41);
    assert.equal(app.calls.play, 1);
    assert.equal(app.audio.paused, true);

    // Position follows rate/seek; invalid and unloaded media clears stale position.
    app.audio.playbackRate = 1.5;
    app.emit("ratechange");
    assert.deepEqual(app.positions.at(-1), { duration: 90, position: 41, playbackRate: 1.5 });
    app.audio.duration = NaN;
    app.audio.readyState = 0;
    app.emit("emptied");
    assert.equal(app.positions.at(-1), undefined);
    app.handlers.seekto({ seekTime: 55 });
    assert.equal(app.audio.currentTime, 41, "Unknown source bounds must not receive a stale seek");
    app.audio.duration = 90;
    app.audio.readyState = 1;
    app.emit("loadedmetadata");
    app.handlers.stop();
    assert.equal(app.audio.currentTime, 0);
    assert.equal(app.session.playbackState, "paused");

    // Clearing/releasing a session removes metadata, handlers and event writers.
    app.setSong(null);
    assert.equal(app.session.metadata, null);
    assert.equal(app.session.playbackState, "none");
    assert.equal(app.handlers.play, null);
    app.controller.destroy();
    app.controller.destroy();
    const positionCount = app.positions.length;
    app.emit("timeupdate");
    app.controller.refresh();
    assert.equal(app.positions.length, positionCount);
    assert.ok(Object.values(app.handlers).every(value => value === null));
    console.log("Media Session action, metadata, position, lifecycle and fallback checks passed");
  } finally {
    if (originalNavigator) Object.defineProperty(globalThis, "navigator", originalNavigator);
    else delete globalThis.navigator;
    if (originalMetadata === undefined) delete globalThis.MediaMetadata;
    else globalThis.MediaMetadata = originalMetadata;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
