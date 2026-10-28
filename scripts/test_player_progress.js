#!/usr/bin/env node
"use strict";

// Exercise the real initializer and event handlers. The media element seam
// records seeks separately from transport calls: seeking must never autoplay.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../assets/song.js"), "utf8");
const start = source.indexOf("function fmtTime(");
const end = source.indexOf("function snapshotGlobals()", start);
function element() {
  const handlers = new Map();
  return {
    dataset: {}, attrs: {}, style: {}, classList: { toggle() {} },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    addEventListener(k, fn) { if (!handlers.has(k)) handlers.set(k, []); handlers.get(k).push(fn); },
    emit(k, detail = {}) { for (const fn of handlers.get(k) || []) fn(detail); },
    getBoundingClientRect() { return { left: 10, width: 100 }; },
    setPointerCapture() {}, releasePointerCapture() {},
  };
}
function setup(length = 125) {
  const ids = Object.fromEntries(["songAudio", "apPlayPause", "apProgress", "apProgressBar", "apElapsed", "apDuration"].map(id => [id, element()]));
  const controls = [];
  ids.apPlayPause.before = control => controls.unshift(control);
  ids.apPlayPause.after = control => controls.push(control);
  const audio = ids.songAudio;
  Object.assign(audio, { duration: length, currentTime: 30, paused: true });
  let transportCalls = 0;
  const document = { getElementById: id => ids[id], createElement: () => element(), addEventListener() {} };
  vm.runInNewContext(source.slice(start, end) + "setupAudioPlayer(); setupAudioPlayer();", { document, getPlaybackController: () => ({
    isPlaying: () => false, isPending: () => false,
    play() { transportCalls++; }, pause() { transportCalls++; },
  }) });
  const press = key => {
    let prevented = false;
    ids.apProgress.emit("keydown", { key, preventDefault() { prevented = true; } });
    return prevented;
  };
  return { ...ids, audio, press, controls, transportCalls: () => transportCalls };
}

let app = setup();
assert.equal(app.controls.length, 2, "Reinitializing a persistent player must not duplicate seek buttons");
const [backward, forward] = app.controls;
assert.equal(backward.type, "button");
assert.equal(forward.type, "button");
assert.equal(backward.attrs["aria-label"], "Back 10 seconds");
assert.equal(forward.attrs["aria-label"], "Forward 10 seconds");
backward.emit("click");
assert.equal(app.audio.currentTime, 20);
forward.emit("click");
assert.equal(app.audio.currentTime, 30);
assert.equal(app.audio.paused, true);
assert.equal(app.transportCalls(), 0, "Visible seek buttons must not toggle playback");
assert.equal(app.apProgress.attrs.role, "slider");
assert.equal(app.apProgress.attrs["aria-label"], "Seek");
assert.equal(app.apProgress.attrs["aria-orientation"], "horizontal");
assert.equal(app.apProgress.attrs.tabindex, "0");
assert.equal(app.apProgress.attrs["aria-valuemin"], "0");
assert.equal(app.apProgress.attrs["aria-valuemax"], "125");
assert.equal(app.apProgress.attrs["aria-valuenow"], "30");
assert.match(app.apProgress.attrs["aria-valuetext"], /0:30.*2:05/);
for (const [key, expected] of [["ArrowRight", 40], ["ArrowUp", 50], ["ArrowLeft", 40], ["ArrowDown", 30], ["PageUp", 90], ["PageDown", 30], ["End", 125], ["ArrowRight", 125], ["Home", 0], ["ArrowLeft", 0]]) {
  assert.equal(app.press(key), true);
  assert.equal(app.audio.currentTime, expected, key);
  assert.equal(Number(app.apProgress.attrs["aria-valuenow"]), expected);
}
assert.equal(app.press("x"), false);
assert.equal(app.audio.paused, true);
assert.equal(app.transportCalls(), 0);
app.audio.paused = false;
app.press("ArrowRight");
assert.equal(app.audio.paused, false);
forward.emit("click");
assert.equal(app.audio.currentTime, 20);
assert.equal(app.audio.paused, false);
assert.equal(app.transportCalls(), 0);
app.audio.currentTime = 62.5;
app.audio.emit("timeupdate");
assert.equal(app.apProgressBar.style.width, "50%");
assert.equal(app.apProgress.attrs["aria-valuenow"], "62.5");
app.apProgress.emit("pointerdown", { clientX: 200, pointerId: 1, button: 0 });
assert.equal(app.audio.currentTime, 125);
app.apProgress.emit("pointerup", { pointerId: 1 });
app.apProgress.emit("pointerdown", { clientX: -50, pointerId: 2, button: 0 });
assert.equal(app.audio.currentTime, 0);
app.apProgress.emit("pointerup", { pointerId: 2 });
backward.emit("click");
assert.equal(app.audio.currentTime, 0, "Back clamps at the start");
app.audio.currentTime = 120;
forward.emit("click");
assert.equal(app.audio.currentTime, 125, "Forward clamps at the end");
assert.equal(app.transportCalls(), 0);

for (const duration of [NaN, Infinity, 0, -1]) {
  app = setup(duration);
  assert.equal(app.apProgress.attrs["aria-disabled"], "true");
  for (const button of app.controls) {
    assert.equal(button.disabled, true, "No duration means no visible seeking");
    button.emit("click");
  }
  app.press("End");
  app.apProgress.emit("pointerdown", { clientX: 50, pointerId: 1, button: 0 });
  assert.equal(app.audio.currentTime, 30, `Unseekable duration ${duration}`);
  assert.equal(app.apProgressBar.style.width, "0%");
  assert.equal(app.transportCalls(), 0);
  app.audio.duration = 120;
  app.audio.emit("loadedmetadata");
  assert.ok(app.controls.every(button => button.disabled === false));
  assert.equal(app.apProgress.attrs["aria-disabled"], "false");
  assert.equal(app.apProgress.attrs["aria-valuemax"], "120");
  app.press("End");
  assert.equal(app.audio.currentTime, 120);
}
console.log("Progress slider and visible 10-second controls preserve transport state and finite bounds");
