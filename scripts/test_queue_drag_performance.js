#!/usr/bin/env node
"use strict";

// Production event handling with controlled frames: a burst of movement must
// consume one latest coordinate, and release must flush before committing order.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.env.APP_SOURCE || require.resolve("../assets/app.js"), "utf8");
const frames = new Map(); let nextFrame = 0;
const moves = []; const handlers = new Map();
const context = vm.createContext({
  dragMoveFrame: 0, pendingDragPoint: null, draggedRow: {}, dragActive: true,
  dragPointerId: 7, dragStartX: 0, dragStartY: 0, DRAG_SLOP_PX: 12,
  requestAnimationFrame(fn) { frames.set(++nextFrame, fn); return nextFrame; },
  cancelAnimationFrame(id) { frames.delete(id); },
  moveDraggedRow(x, y) { moves.push([x, y]); }, resetDragGesture() {},
  queueSheet: { addEventListener(name, fn) { handlers.set(name, fn); } },
});
const scheduler = source.indexOf("  const flushDragMove =");
if (scheduler >= 0) vm.runInContext(source.slice(scheduler, source.indexOf("  const startDragGesture =", scheduler)), context);
const listener = source.indexOf('  queueSheet.addEventListener("pointermove"');
vm.runInContext(source.slice(listener, source.indexOf("  const touchById =", listener)), context);
for (let index = 0; index < 100; index++) handlers.get("pointermove")({ pointerId: 7, clientX: index, clientY: index * 2, preventDefault() {} });
assert.equal(moves.length, 0, "Pointer bursts must not synchronously perform layout per event");
assert.equal(frames.size, 1);
[...frames.values()][0]();
assert.deepEqual(moves, [[99, 198]], "One frame consumes only the latest coordinates");
assert.equal(frames.size, 0);
handlers.get("pointermove")({ pointerId: 7, clientX: 104, clientY: 208, preventDefault() {} });
vm.runInContext("flushDragMove()", context);
assert.deepEqual(moves, [[99, 198], [104, 208]], "Release flush retains a last movement before the next frame");
assert.equal(frames.size, 0);

// FLIP geometry must be read as one batch, before any row transform writes.
const events = [];
const list = {};
const row = top => ({ parentElement: list, isConnected: true,
  classList: { contains: () => false },
  getBoundingClientRect() { events.push("read"); return { top }; },
  style: new Proxy({}, { set(object, key, value) { events.push("write"); object[key] = value; return true; } }),
});
const first = row(10), second = row(20);
context.matchMedia = () => ({ matches: false });
const animation = source.indexOf("  const animateQueueReorder =");
vm.runInContext(source.slice(animation, source.indexOf("  const renderQueuePill =", animation)), context);
context.list = list; context.before = new Map([[first, { top: 20 }], [second, { top: 10 }]]);
vm.runInContext("animateQueueReorder(list, before)", context);
assert.deepEqual(events.slice(0, 2), ["read", "read"]);
assert.ok(events.slice(2).every(event => event === "write"));
assert.equal(frames.size, 1, "All visible transforms settle together");
console.log("Playlist pointer coalescing, release flush and batched layout passed");
