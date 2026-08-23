#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");

const song = (slug, queueId = slug.slice(0, 8)) => ({
  slug,
  queueId,
  title: slug.toUpperCase(),
  credit: `${slug} singer`,
  audioSources: [{ src: `/audio/${slug}.m4a`, type: "audio/mp4" }],
});

const a = song("alpha-song", "00000001");
const b = song("beta-song", "00000002");
const c = song("gamma-song", "00000003");
const d = song("delta-song", "00000004");
const catalogue = new Map([a, b, c, d].map(item => [item.queueId, item]));
global.window = { BHAKTI_SONGS: [a, b, c, d] };
const Queue = require("../assets/queue.js");

const slugs = state => state.items.map(item => item.slug);
const make = (items, currentIndex = 0, mode = "custom") =>
  Queue.create({ mode, items, currentIndex, sessionId: "session-1" });

assert.throws(() => Queue.create({ mode: "custom", items: [], currentIndex: 0, sessionId: "s" }), /non-empty/);
const duplicateSongs = make([a, a]);
assert.deepEqual(slugs(duplicateSongs), ["alpha-song", "alpha-song"]);
assert.equal(new Set(duplicateSongs.items.map(item => item.entryId)).size, 2);
assert.throws(() => make([{...a, entryId: "same"}, {...b, entryId: "same"}]), /entry IDs must be unique/);
assert.throws(() => make([a], -1), /currentIndex/);
assert.throws(() => make([a], 1), /currentIndex/);
assert.throws(() => make([a, b], 0, "standalone"), /exactly one/);
assert.throws(() => Queue.create({ mode: "custom", items: [a], currentIndex: 0, sessionId: "" }), /sessionId/);
assert.throws(() => make([{ ...a, queueId: "" }]), /queueId/);

const frozen = make([a, b]);
assert.equal(Object.isFrozen(frozen), true);
assert.equal(Object.isFrozen(frozen.items), true);
assert.equal(Object.isFrozen(frozen.items[0]), true);
assert.notEqual(frozen.items[0], a);

const standalone = Queue.standalone(a, "session-1");
assert.deepEqual(slugs(standalone), ["alpha-song"]);
assert.equal(standalone.mode, "standalone");
assert.equal(standalone.currentIndex, 0);

let state = make([a, b, c]);
state = Queue.playNow(state, d);
assert.deepEqual(slugs(state), ["alpha-song", "delta-song", "beta-song", "gamma-song"]);
assert.equal(state.currentIndex, 1);

state = Queue.playNow(state, state.items.find(item => item.slug === c.slug));
assert.deepEqual(slugs(state), ["alpha-song", "delta-song", "gamma-song", "beta-song"]);
assert.equal(state.currentIndex, 2);

state = Queue.playNow(state, state.items.find(item => item.slug === a.slug));
assert.deepEqual(slugs(state), ["delta-song", "gamma-song", "alpha-song", "beta-song"]);
assert.equal(state.currentIndex, 2);
assert.equal(Queue.playNow(state, state.items[state.currentIndex]), state);

state = Queue.append(make([a, b, c], 1), d);
assert.deepEqual(slugs(state), ["alpha-song", "beta-song", "gamma-song", "delta-song"]);
state = Queue.append(state, c);
assert.deepEqual(slugs(state), ["alpha-song", "beta-song", "gamma-song", "delta-song", "gamma-song"]);
assert.notEqual(state.items[2].entryId, state.items[4].entryId);

state = make([a, b, c, d], 0);
state = Queue.move(state, 3, 1);
assert.deepEqual(slugs(state), ["alpha-song", "delta-song", "beta-song", "gamma-song"]);
state = Queue.move(state, 1, 3);
assert.deepEqual(slugs(state), ["alpha-song", "beta-song", "gamma-song", "delta-song"]);
assert.throws(() => Queue.move(state, 0, 2), /upcoming/);
assert.throws(() => Queue.move(state, 2, 0), /upcoming/);
assert.throws(() => Queue.move(state, 9, 2), /index/);

state = Queue.remove(make([a, b, c], 0), 1);
assert.deepEqual(slugs(state), ["alpha-song", "gamma-song"]);
assert.throws(() => Queue.remove(state, 0), /current or played/);
assert.throws(() => Queue.remove(state, 8), /index/);

state = make([a, b, c, d], 1);
const [cEntryId, dEntryId] = state.items.slice(2).map(item => item.entryId);
state = Queue.reorderUpcoming(state, [dEntryId, cEntryId]);
assert.deepEqual(slugs(state), ["alpha-song", "beta-song", "delta-song", "gamma-song"]);
for (const invalidOrder of [
  [cEntryId],
  [cEntryId, cEntryId],
  [state.items[0].entryId, cEntryId],
]) {
  assert.throws(() => Queue.reorderUpcoming(state, invalidOrder), /upcoming order/);
}

let advance = Queue.advance(make([a, b], 0));
assert.equal(advance.advanced, true);
assert.equal(advance.state.currentIndex, 1);
advance = Queue.advance(advance.state);
assert.equal(advance.advanced, false);
assert.equal(advance.state, advance.state);

state = make([a, b, c], 0);
const failedAttempts = [];
while (true) {
  failedAttempts.push(state.items[state.currentIndex].entryId);
  const next = Queue.advance(state);
  if (!next.advanced) break;
  state = next.state;
}
assert.equal(failedAttempts.length, 3);
assert.equal(new Set(failedAttempts).size, 3);

const deterministic = [0.2, 0.8, 0.1];
let randomIndex = 0;
state = Queue.shuffle([a, b, c, d], () => deterministic[randomIndex++], "shuffle-session");
assert.equal(state.mode, "shuffle");
assert.equal(state.currentIndex, 0);
assert.deepEqual([...slugs(state)].sort(), ["alpha-song", "beta-song", "delta-song", "gamma-song"]);
assert.equal(new Set(slugs(state)).size, 4);
const duplicateShuffle = Queue.shuffle([a, a], Math.random, "s");
assert.deepEqual(slugs(duplicateShuffle), ["alpha-song", "alpha-song"]);
assert.equal(new Set(duplicateShuffle.items.map(item => item.entryId)).size, 2);

state = make([a, b, c, d], 1, "shuffle");
randomIndex = 0;
const reshuffled = Queue.shuffleRemaining(state, () => deterministic[randomIndex++]);
assert.deepEqual(slugs(reshuffled).slice(0, 2), ["alpha-song", "beta-song"]);
assert.deepEqual(slugs(reshuffled).slice(2).sort(), ["delta-song", "gamma-song"]);

state = make([a, b, c], 1, "shuffle");
const payload = Queue.encode(state);
assert.match(payload, /^[A-Za-z0-9_-]+$/);
assert.ok(payload.length <= 12, `3-song compact payload unexpectedly long: ${payload.length}`);
const decoded = Queue.decode(payload, catalogue, "received-session", 4);
assert.deepEqual(slugs(decoded), slugs(state));
assert.equal(decoded.currentIndex, 1);
assert.equal(decoded.mode, "shuffle");
assert.equal(decoded.sessionId, "received-session");

const encodedObject = value => Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
const legacyPayload = encodedObject({ v: 1, m: "shuffle", q: state.items.map(item => item.queueId), i: 1 });
const legacyDecoded = Queue.decode(legacyPayload, catalogue, "legacy-session", 4);
assert.deepEqual(slugs(legacyDecoded), slugs(state));
assert.equal(legacyDecoded.sessionId, "legacy-session");
for (const invalid of [
  "not-base64!",
  encodedObject({ v: 2, m: "custom", q: [a.queueId], i: 0 }),
  encodedObject({ v: 1, m: "standalone", q: [a.queueId, b.queueId], i: 0 }),
  encodedObject({ v: 1, m: "custom", q: ["ffffffff"], i: 0 }),
  encodedObject({ v: 1, m: "custom", q: [a.queueId], i: 2 }),
  encodedObject({ v: 1, m: "custom", q: [a.queueId, b.queueId, c.queueId], i: 0 }),
]) {
  assert.equal(Queue.decode(invalid, catalogue, "s", 2), null);
}
assert.equal(Queue.decode("a".repeat(4097), catalogue, "s", 4), null);
const duplicatePayload = encodedObject({ v: 1, m: "custom", q: [a.queueId, a.queueId], i: 1 });
const duplicateRoundTrip = Queue.decode(duplicatePayload, catalogue, "duplicate-session", 4);
assert.deepEqual(slugs(duplicateRoundTrip), ["alpha-song", "alpha-song"]);
assert.equal(new Set(duplicateRoundTrip.items.map(item => item.entryId)).size, 2);

const restored = Queue.restore(JSON.stringify(state), catalogue);
assert.deepEqual(slugs(restored), slugs(state));
assert.equal(restored.sessionId, state.sessionId);
assert.equal(Queue.restore("not json", catalogue), null);
assert.equal(Queue.restore(JSON.stringify({ ...state, items: [{ ...a, queueId: "ffffffff" }] }), catalogue), null);

const fullCatalogue = Array.from({ length: 229 }, (_, index) => song(
  `song-${String(index).padStart(3, "0")}`,
  index.toString(16).padStart(8, "0"),
));
global.window.BHAKTI_SONGS = fullCatalogue;
const fullState = Queue.create({
  mode: "shuffle",
  items: fullCatalogue,
  currentIndex: 117,
  sessionId: "full-catalogue-session",
});
const fullPayload = Queue.encode(fullState);
assert.ok(fullPayload.length < 4000, `full catalogue payload is unexpectedly long: ${fullPayload.length}`);
const fullRoundTrip = Queue.decode(
  fullPayload,
  new Map(fullCatalogue.map(item => [item.queueId, item])),
  "received-full-catalogue",
  229,
);
assert.equal(fullRoundTrip.items.length, 229);
assert.equal(fullRoundTrip.currentIndex, 117);
assert.deepEqual(slugs(fullRoundTrip), slugs(fullState));

const seededFullState = Queue.shuffle(fullCatalogue, () => 0.314159, "seeded-full-session");
const seededFullPayload = Queue.encode(seededFullState);
assert.ok(seededFullPayload.length <= 11, `full-catalogue seeded payload unexpectedly long: ${seededFullPayload.length}`);
const seededFullRoundTrip = Queue.decode(
  seededFullPayload,
  new Map(fullCatalogue.map(item => [item.queueId, item])),
  "seeded-full-received",
  229,
);
assert.deepEqual(slugs(seededFullRoundTrip), slugs(seededFullState));
assert.equal(seededFullRoundTrip.shuffleSeed, seededFullState.shuffleSeed);
assert.equal(seededFullRoundTrip.shuffleAll, true);
assert.equal(Queue.decode(seededFullPayload.slice(0, -1), new Map(fullCatalogue.map(item => [item.queueId, item])), "truncated", 229), null);
const reorderedCatalogue = [fullCatalogue[1], fullCatalogue[0], ...fullCatalogue.slice(2)];
assert.equal(
  Queue.decode(seededFullPayload, new Map(reorderedCatalogue.map(item => [item.queueId, item])), "wrong-catalogue", 229),
  null,
);
const restoredSeeded = Queue.restore(JSON.stringify(seededFullState), new Map(fullCatalogue.map(item => [item.queueId, item])));
assert.equal(restoredSeeded.shuffleSeed, seededFullState.shuffleSeed);
assert.equal(Queue.encode(restoredSeeded), seededFullPayload);
const advancedSeeded = Queue.advance(seededFullState).state;
assert.equal(advancedSeeded.shuffleAll, true);
assert.ok(Queue.encode(advancedSeeded).length <= 12);
const modifiedSeeded = Queue.remove(seededFullState, 1);
assert.equal(modifiedSeeded.shuffleAll, false);
assert.equal(modifiedSeeded.shuffleSeed, null);
const movedSeeded = Queue.move(seededFullState, 1, 3);
assert.equal(movedSeeded.shuffleAll, true);
const movedSeededPayload = Queue.encode(movedSeeded);
assert.ok(movedSeededPayload.length <= 16, `single-move seeded payload unexpectedly long: ${movedSeededPayload.length}`);
assert.deepEqual(
  slugs(Queue.decode(movedSeededPayload, new Map(fullCatalogue.map(item => [item.queueId, item])), "moved-seeded", 229)),
  slugs(movedSeeded),
);
const reverseOrderedShuffle = Queue.shuffle([...fullCatalogue].reverse(), () => 0.314159, "reverse-session");
assert.equal(reverseOrderedShuffle.shuffleAll, true);
assert.deepEqual(slugs(reverseOrderedShuffle), slugs(seededFullState));

const mediumState = Queue.create({
  mode: "custom",
  items: fullCatalogue.slice(12, 18),
  currentIndex: 2,
  sessionId: "medium-session",
});
const mediumPayload = Queue.encode(mediumState);
assert.ok(mediumPayload.length <= 16, `6-song compact payload unexpectedly long: ${mediumPayload.length}`);
assert.deepEqual(
  slugs(Queue.decode(mediumPayload, new Map(fullCatalogue.map(item => [item.queueId, item])), "medium-received", 229)),
  slugs(mediumState),
);

process.stdout.write("queue state and sharing contract: ok\n");
