#!/usr/bin/env node
"use strict";

// Listener-visible sequence operations, including persisted history and repeated
// occurrences. No media mocks: these operations must not touch the audio node.
const assert = require("node:assert/strict");
const Queue = require("../assets/queue.js");
const song = slug => ({slug, queueId: slug, title: slug, audioSources: []});
const [a, b, c, d, e] = ["a", "b", "c", "d", "e"].map(song);
const catalogue = new Map([a, b, c, d, e].map(item => [item.queueId, item]));
const create = (items, currentIndex = 0) => Queue.create({mode: "custom", items, currentIndex, sessionId: "session"});
const ids = state => state.items.map(item => item.slug);

const before = create([a, b, c, d], 1);
const next = Queue.playNext(before, e, "unused");
assert.deepEqual(ids(next), ["a", "b", "e", "c", "d"]);
assert.equal(next.currentIndex, 1);
assert.equal(next.sessionId, before.sessionId);
assert.deepEqual(next.items.slice(0, 2), before.items.slice(0, 2));
assert.deepEqual(ids(before), ["a", "b", "c", "d"]);
assert.equal(Queue.advance(next).state.items[2].slug, "e");

const duplicate = Queue.playNext(before, before.items[1]);
assert.deepEqual(ids(duplicate), ["a", "b", "b", "c", "d"]);
assert.notEqual(duplicate.items[1].entryId, duplicate.items[2].entryId);
assert.deepEqual(ids(Queue.append(before, e)), ["a", "b", "c", "d", "e"]);

// With no current session, both choices prepare the first song; app remains
// responsible for loading it without autoplay, just like existing append.
const initial = Queue.playNext(null, a, "first");
assert.deepEqual(ids(initial), ["a"]);
assert.equal(initial.currentIndex, 0);
assert.equal(initial.sessionId, "first");
assert.equal(initial.mode, "custom");
const last = create([a, b], 1);
assert.deepEqual(ids(Queue.playNext(last, c)), ["a", "b", "c"]);
assert.deepEqual(ids(Queue.playNext(Queue.standalone(a, "solo"), b)), ["a", "b"]);

// Opening a different standalone song retains the first occurrence and session.
// Returning to the same song later creates a distinct occurrence, not a dedupe.
const solo = Queue.standalone(a, "solo");
const secondSong = Queue.playNow(solo, b);
assert.deepEqual(ids(secondSong), ["a", "b"]);
assert.equal(secondSong.currentIndex, 1);
assert.equal(secondSong.mode, "custom");
assert.equal(secondSong.sessionId, "solo");
assert.equal(secondSong.items[0].entryId, solo.items[0].entryId);
const returnVisit = Queue.playNow(secondSong, a);
assert.deepEqual(ids(returnVisit), ["a", "b", "a"]);
assert.notEqual(returnVisit.items[0].entryId, returnVisit.items[2].entryId);
assert.deepEqual(ids(Queue.restore(JSON.stringify(returnVisit), catalogue)), ["a", "b", "a"]);
assert.deepEqual(ids(secondSong), ["a", "b"], "Revisiting a song must not rewrite the earlier session");

// The number of occurrences can exceed the catalogue size: repeated listening
// still shares its full ordered history and current occurrence.
const longHistory = create([a, b, a, b, a, b, a, b], 6);
const longHistoryShared = Queue.decode(Queue.encode(longHistory), catalogue, "received");
assert.ok(longHistoryShared, "Repeated history must be shareable beyond catalogue size");
assert.deepEqual(ids(longHistoryShared), ["a", "b", "a", "b", "a", "b", "a", "b"]);
assert.equal(longHistoryShared.currentIndex, 6);
assert.equal(new Set(longHistoryShared.items.map(item => item.entryId)).size, 8);

assert.equal(Queue.clearUpcoming(null), null);
assert.deepEqual(Queue.previous(null), {state: null, moved: false});
const cleared = Queue.clearUpcoming(before);
assert.deepEqual(ids(cleared), ["a", "b"]);
assert.equal(cleared.currentIndex, 1);
assert.deepEqual(cleared.items, before.items.slice(0, 2));
assert.equal(Queue.advance(cleared).advanced, false);
assert.deepEqual(Queue.clearUpcoming(cleared), cleared);
assert.deepEqual(Queue.clearUpcoming(initial), initial);
const previous = Queue.previous(cleared);
assert.equal(previous.moved, true);
assert.equal(previous.state.currentIndex, 0);
assert.deepEqual(previous.state.items, cleared.items);
assert.equal(Queue.previous(previous.state).moved, false);
assert.equal(Queue.advance(previous.state).state.items[1].slug, "b");

// Real JSON persistence/restore, including legacy VERSION 1 session shape.
const shared = Queue.decode(Queue.encode(cleared), catalogue, "reload-session", catalogue.size);
assert.deepEqual(ids(shared), ["a", "b"]);
assert.equal(shared.currentIndex, 1);
assert.equal(Queue.previous(shared).state.items[0].slug, "a");
const restored = Queue.restore(JSON.stringify(cleared), catalogue);
assert.equal(Queue.previous(restored).state.items[0].slug, "a");
const repeated = Queue.advance(Queue.playNext(create([a, b]), a)).state;
const repeatedRestored = Queue.restore(JSON.stringify(repeated), catalogue);
assert.notEqual(repeatedRestored.items[0].entryId, repeatedRestored.items[1].entryId);
assert.equal(Queue.previous(repeatedRestored).state.currentIndex, 0);
assert.equal(Queue.advance(Queue.previous(repeatedRestored).state).state.currentIndex, 1);
// Selecting a visible played occurrence moves the cursor without rewriting
// listening order, including when the same song occurred more than once.
const historyState = create([a, b, a, c], 2);
const historySelected = Queue.selectHistory(historyState, 0);
assert.equal(historySelected.currentIndex, 0);
assert.deepEqual(historySelected.items, historyState.items);
assert.equal(historySelected.sessionId, historyState.sessionId);
assert.throws(() => Queue.selectHistory(historyState, 2), /played/);
assert.throws(() => Queue.selectHistory(historyState, 3), /played/);
assert.throws(() => Queue.selectHistory(historyState, -1), /range/);
const historyCleared = Queue.clearUpcoming(historyState);
const historyReloaded = Queue.restore(JSON.stringify(historyCleared), catalogue);
assert.deepEqual(historyReloaded.items.slice(0, historyReloaded.currentIndex).map(item => item.title), ["a", "b"]);
assert.deepEqual(Queue.selectHistory(historyReloaded, 1).items, historyReloaded.items);
// Remove by occurrence, including repeated titles before the cursor. The
// playing entry, future order and old immutable state must remain intact.
const removedHistory = Queue.remove(historyState, 0);
assert.deepEqual(ids(removedHistory), ["b", "a", "c"]);
assert.equal(removedHistory.currentIndex, 1);
assert.equal(removedHistory.items[1].entryId, historyState.items[2].entryId);
assert.deepEqual(ids(historyState), ["a", "b", "a", "c"]);
assert.throws(() => Queue.remove(historyState, 2), /current/);
assert.equal(Queue.restore(JSON.stringify(removedHistory), catalogue).currentIndex, 1);

// Repeat is session-local; completion, explicit Next and failures have
// different outcomes. Repeating never manufactures queue occurrences.
assert.equal(before.repeat, "off");
const one = Queue.cycleRepeat(before);
assert.equal(one.repeat, "one");
assert.equal(Queue.advance(one, { reason: "ended" }).state, one);
assert.equal(Queue.advance(one, { reason: "ended" }).advanced, true);
assert.equal(Queue.advance(one).state.currentIndex, 2, "Next bypasses repeat-one");
assert.equal(Queue.advance(Queue.create({ ...one, currentIndex: 3 })).advanced, false);
assert.equal(Queue.advance(one, { reason: "failed" }).state.currentIndex, 2);
const all = Queue.cycleRepeat(one);
assert.equal(all.repeat, "all");
assert.equal(Queue.cycleRepeat(all).repeat, "off");
assert.equal(Queue.advance(all, { reason: "ended" }).state.currentIndex, 2);
const allLast = Queue.create({ ...all, currentIndex: 3 });
for (const reason of ["ended", "next"]) {
  const wrapped = Queue.advance(allLast, { reason });
  assert.equal(wrapped.advanced, true);
  assert.equal(wrapped.state.currentIndex, 0);
  assert.deepEqual(wrapped.state.items, allLast.items);
  assert.equal(wrapped.state.sessionId, allLast.sessionId);
  assert.equal(wrapped.state.repeat, "all");
}
for (const repeat of ["off", "one", "all"]) {
  const final = Queue.create({ ...allLast, repeat });
  assert.equal(Queue.advance(final, { reason: "failed" }).advanced, false);
  assert.equal(Queue.advance(final, { reason: "ended" }).advanced, repeat !== "off");
  const single = Queue.create({ ...solo, repeat });
  assert.equal(Queue.advance(single, { reason: "ended" }).advanced, repeat !== "off");
  assert.equal(Queue.advance(single, { reason: "failed" }).advanced, false);
  assert.equal(Queue.advance(single).advanced, repeat === "all");
}
for (const changed of [Queue.remove(all, 0), Queue.append(all, e),
  Queue.playNext(all, e), Queue.clearUpcoming(all), Queue.previous(all).state,
  Queue.move(all, 2, 3), Queue.shuffleRemaining(all, () => 0.5), Queue.playNow(all, e)]) {
  assert.equal(changed.repeat, "all", "Queue edits preserve repeat");
}
assert.equal(Queue.restore(JSON.stringify(one), catalogue).repeat, "one");
const legacySession = { ...before };
delete legacySession.repeat;
assert.equal(Queue.restore(JSON.stringify(legacySession), catalogue).repeat, "off");
assert.equal(Queue.decode(Queue.encode(one), catalogue, "recipient").repeat, "off");
assert.equal(Queue.shuffle([a, b, c], () => 0.5, "new-session").repeat, "off");
assert.throws(() => Queue.create({ ...before, repeat: "invalid" }), /repeat/);
console.log("Queue controls, repeat and persisted history passed");
