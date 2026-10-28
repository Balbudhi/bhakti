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

// A short ordinary click retains the existing About interaction.
{
  const f = fixture(); f.emit("pointerdown"); f.tick(1999); f.emit("pointerup"); f.tick(5000);
  assert.deepEqual(f.opened, []); assert.equal(f.emit("click").prevented, false);
}
{
  const f = fixture(); f.emit("pointerdown"); f.tick(2000);
  assert.deepEqual(f.opened, ["https://owner.bhakti.eeshan.xyz/"]);
  f.tick(5000); assert.equal(f.opened.length, 1);
  const trailing = f.emit("click"); assert.equal(trailing.prevented, true); assert.equal(trailing.stopped, true);
  f.emit("pageshow"); f.emit("pointerdown"); f.tick(2000); assert.equal(f.opened.length, 2);
}
for (const cancel of ["pointerup", "pointercancel", "blur", "resize"]) {
  const f = fixture(); f.emit("pointerdown"); f.tick(1000); f.emit(cancel); f.tick(2000);
  assert.equal(f.opened.length, 0, cancel);
}
{
  const f = fixture(); f.emit("pointerdown"); f.document.hidden = true; f.emit("visibilitychange"); f.tick(2000);
  assert.equal(f.opened.length, 0);
}
{
  const f = fixture(); f.emit("pointerdown"); f.emit("pointermove", { clientX: 23 }); f.tick(2000);
  assert.equal(f.opened.length, 0, "Scrolling/movement cancels the hold");
}
for (const extra of [{ button: 2 }, { isPrimary: false }, { target: { closest: () => null } }]) {
  const f = fixture(); f.emit("pointerdown", extra); f.tick(2000); assert.equal(f.opened.length, 0);
}
{
  const f = fixture(); const e = f.emit("keydown", { altKey: true, shiftKey: true, code: "KeyO" });
  assert.equal(e.prevented, true); assert.equal(f.opened.length, 1);
}
for (const extra of [{ repeat: true }, { ctrlKey: true }, { metaKey: true }, { target: { closest: () => ({}) } }]) {
  const f = fixture(); f.emit("keydown", { altKey: true, shiftKey: true, code: "KeyO", ...extra });
  assert.equal(f.opened.length, 0, "Shortcut cannot steal editing or repeated key input");
}
console.log("PASS: discreet owner entry, cancellation, ordinary clicks, keyboard and restored-page behavior");
