#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../assets/owner-entry.js"), "utf8");

function fixture() {
  const handlers = new Map();
  const timers = new Map();
  const opened = [];
  let now = 0, sequence = 0;
  const on = (type, fn) => { if (!handlers.has(type)) handlers.set(type, []); handlers.get(type).push(fn); };
  const document = { hidden: false, addEventListener: on };
  const window = { addEventListener: on, location: { assign: url => opened.push(url) } };
  vm.runInNewContext(source, { document, window,
    setTimeout(fn, delay) { const id = ++sequence; timers.set(id, { at: now + delay, fn }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  const about = { closest: selector => selector === "#aboutToggle" ? about : null };
  const emit = (type, extra = {}) => {
    const event = { target: about, button: 0, isPrimary: true, pointerId: 1, clientX: 10, clientY: 10,
      prevented: false, stopped: false, preventDefault() { this.prevented = true; },
      stopImmediatePropagation() { this.stopped = true; }, ...extra };
    for (const fn of handlers.get(type) || []) fn(event);
    return event;
  };
  const tick = ms => { now += ms; for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); } };
  return { document, emit, tick, opened };
}

// Native links provide ordinary tap, keyboard and browser navigation semantics.
// The owner link belongs inside the hidden About panel, not permanent navigation.
const html = fs.readFileSync(path.join(__dirname, "../index.html"), "utf8");
const panel = html.match(/<aside\b[^>]*id="aboutPanel"[^>]*>[\s\S]*?<\/aside>/)?.[0];
assert.ok(panel && /<aside[^>]*\bhidden\b/.test(panel));
assert.match(panel, /<a\b[^>]*class="owner-entry"[^>]*href="https:\/\/owner\.bhakti\.eeshan\.xyz\/"[^>]*>Owner sign in<\/a>/);
// Holding must never navigate, consume clicks, or suppress native browser behavior.
{
  const f = fixture(); f.emit("pointerdown"); f.tick(10000);
  assert.deepEqual(f.opened, [], "No time-based pointer navigation");
  f.emit("pointerup");
  assert.equal(f.emit("click").prevented, false);
  assert.equal(f.emit("contextmenu").prevented, false);
}
{
  const f = fixture(); const e = f.emit("keydown", { altKey: true, shiftKey: true, code: "KeyO" });
  assert.equal(e.prevented, true); assert.equal(f.opened.length, 1);
}
for (const extra of [{ repeat: true }, { ctrlKey: true }, { metaKey: true }, { target: { closest: () => ({}) } }]) {
  const f = fixture(); f.emit("keydown", { altKey: true, shiftKey: true, code: "KeyO", ...extra });
  assert.equal(f.opened.length, 0, "Shortcut cannot steal editing or repeated key input");
}
{
  const f = fixture();
  const key = { altKey: true, shiftKey: true, code: "KeyO" };
  f.emit("keydown", key); f.emit("keydown", key);
  assert.equal(f.opened.length, 1);
  f.emit("pageshow"); f.emit("keydown", key);
  assert.equal(f.opened.length, 2, "Back/Forward restores shortcut");
}
console.log("PASS: native disclosed owner link, no long-press navigation, keyboard and restored-page behavior");
