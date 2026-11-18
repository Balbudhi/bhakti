#!/usr/bin/env node
"use strict";

// The real renderer runs against jsdom's parser/tree/focus implementation.
// This verifies DOM ownership, not browser layout or physical touch behavior.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const Queue = require("../assets/queue.js");
const source = fs.readFileSync(require.resolve("../assets/app.js"), "utf8");
const dom = new JSDOM("<!doctype html><body><section id='queue'></section></body>");
const { document } = dom.window;
const sheet = document.getElementById("queue");
const context = vm.createContext({ document, queueSheet: sheet,
  queueState: null, draggedRow: null, resetDragGesture() {},
  playback: { isPlaying: () => false, isPending: () => false },
  escapeHtml: value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
  CSS: { escape: value => value },
});
vm.runInContext(source.slice(source.indexOf("  const playIcon ="), source.indexOf("  const revealCurrentQueueRow =")), context);
const render = state => { context.queueState = state; vm.runInContext("renderQueueSheet()", context); };
const song = slug => ({ slug, queueId: slug, title: `Śrī ${slug}`, credit: "Singer", audioSources: [] });
let state = Queue.create({ mode: "custom", items: [song("a"), song("b"), song("a"), song("c")], currentIndex: 1, sessionId: "test" });
const rows = () => [...sheet.querySelectorAll(".queue-row")];
const rowFor = entry => sheet.querySelector(`[data-queue-entry-id="${entry}"]`);
const order = () => rows().map(row => row.dataset.queueEntryId);
render(state);
const originalRows = rows();
const list = sheet.querySelector(".queue-list");
const play = sheet.querySelector('[data-queue-action="queue-play"]');
const handle = originalRows[2].querySelector("[data-queue-drag]");
handle.focus(); list.scrollTop = 71;
const originalControls = [...sheet.querySelectorAll("button")];
render(Queue.cycleRepeat(state));
assert.equal(sheet.querySelector(".queue-list"), list, "Repeat retains the scroll container");
assert.deepEqual(rows(), originalRows, "Repeat retains occurrence rows");
assert.deepEqual([...sheet.querySelectorAll("button")], originalControls, "Repeat retains controls");
assert.equal(document.activeElement, handle);
assert.equal(list.scrollTop, 71);
render(state); // reopening an unchanged playlist must do no row replacement
assert.deepEqual(rows(), originalRows);

state = Queue.append(state, song("d")); render(state);
assert.deepEqual(rows().slice(0, 4), originalRows);
assert.equal(rows().length, 5);
assert.equal(sheet.querySelector('[data-queue-action="queue-play"]'), play);
state = Queue.move(state, 2, 4); render(state);
assert.deepEqual(order(), state.items.map(item => item.entryId));
assert.equal(rowFor(originalRows[2].dataset.queueEntryId), originalRows[2]);
assert.equal(document.activeElement, handle, "Keyboard reorder retains focus on the moved occurrence");
assert.equal(handle.closest(".queue-row").dataset.queueIndex, "4");

state = Queue.advance(state).state; render(state);
assert.equal(sheet.querySelector('[aria-current="true"]').dataset.queueEntryId, state.items[state.currentIndex].entryId);
assert.ok(originalRows[1].querySelector('[data-queue-action="history"]'));
assert.equal(sheet.querySelectorAll('[aria-current="true"]').length, 1);
// Removing a focused earlier occurrence keeps current identity and provides a
// reachable next focus target even when no matching row remains at that index.
const currentId = state.items[state.currentIndex].entryId;
const remove = originalRows[0].querySelector('[data-queue-action="remove"]');
remove.focus(); state = Queue.remove(state, 0); render(state);
assert.equal(rowFor(originalRows[0].dataset.queueEntryId), null);
assert.equal(state.items[state.currentIndex].entryId, currentId);
assert.ok(sheet.contains(document.activeElement));
assert.notEqual(document.activeElement, document.body);
state = Queue.clearUpcoming(state); render(state);
assert.deepEqual(order(), state.items.map(item => item.entryId));
assert.equal(sheet.querySelector('[data-queue-action="next"]').disabled, true);
render(Queue.cycleRepeat(Queue.cycleRepeat(state)));
assert.equal(sheet.querySelector('[data-queue-action="next"]').disabled, false);
console.log("Playlist retained DOM, order, controls, focus and boundaries passed");
