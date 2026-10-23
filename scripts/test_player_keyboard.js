#!/usr/bin/env node
"use strict";

// Exercise the production document key handler. Native button/summary activation
// is verified in the in-app browser; this test checks whether the handler steals
// that key or touches audio before the browser can perform the native action.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../assets/song.js"), "utf8");
const start = source.indexOf("  // Spacebar play/pause");
const end = source.indexOf("  updateTime();", start);
assert.ok(start >= 0 && end > start, "The production key handler must be present");
let handler;
let mediaCalls = 0;
const audio = { paused: true, play() { mediaCalls++; }, pause() { mediaCalls++; } };
vm.runInNewContext(source.slice(start, end), {
  document: { addEventListener(type, callback) { assert.equal(type, "keydown"); handler = callback; } },
  togglePlayback() { if (audio.paused) audio.play(); else audio.pause(); },
});
function press(target, options = {}) {
  mediaCalls = 0;
  let prevented = false;
  handler({ key: " ", code: "Space", target, preventDefault() { prevented = true; }, ...options });
  return { prevented, mediaCalls };
}
const readingText = { tagName: "DIV", closest: () => null, isContentEditable: false };
assert.deepEqual(press(readingText), { prevented: true, mediaCalls: 1 });
audio.paused = false;
assert.deepEqual(press(readingText), { prevented: true, mediaCalls: 1 });
assert.deepEqual(press(readingText, { key: "Enter", code: "Enter" }), { prevented: false, mediaCalls: 0 });
assert.deepEqual(press(readingText, { defaultPrevented: true }), { prevented: false, mediaCalls: 0 });
for (const selector of ["button", "a", "summary", "input", "textarea", "select", '[role="button"]']) {
  for (const nested of [false, true]) {
    const control = {};
    const target = {
      tagName: nested ? "SVG" : selector.toUpperCase(),
      isContentEditable: false,
      closest: query => query.split(",").map(part => part.trim()).includes(selector) ? control : null,
    };
    assert.deepEqual(press(target), { prevented: false, mediaCalls: 0 }, `${selector}${nested ? " descendant" : ""} must retain its Space action`);
  }
}
assert.deepEqual(press({ ...readingText, isContentEditable: true }), { prevented: false, mediaCalls: 0 });
console.log("Player keyboard shortcut respects interactive controls and handled events");
