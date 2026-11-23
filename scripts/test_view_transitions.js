#!/usr/bin/env node
"use strict";

// Contract: once navigation chooses a new view, an earlier animation cannot
// remove that view or clear its animation/height. Finish the current transition
// before reading roots for the next one; one owner performs all DOM cleanup.
// These tests run production transition code with controlled timers/DOM nodes.
// They establish ordering and resource cleanup, not browser rendering quality.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require.resolve("../assets/app.js"), "utf8");

function setup({ reducedMotion = false } = {}) {
  const timers = new Map();
  let timerId = 0;
  const classes = () => {
    const values = new Set();
    return { add: (...names) => names.forEach(name => values.add(name)),
      remove: (...names) => names.forEach(name => values.delete(name)),
      contains: name => values.has(name), values };
  };
  const style = { height: "", setProperty(name, value) { this[name] = value; },
    removeProperty(name) { delete this[name]; } };
  const stage = { children: [], style, classList: classes(),
    append(node) { node.remove(); this.children.push(node); node.parent = this; },
    querySelector() { return this.children[0] || null; } };
  function node(name) {
    const listeners = new Set();
    return { name, parent: null, classList: classes(), offsetHeight: 100,
      querySelector() { return name === "song" ? {} : null; },
      getBoundingClientRect() { return { left: 0, right: 390 }; },
      remove() {
        if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
        this.parent = null;
      },
      addEventListener(type, listener) { listeners.add(listener); },
      removeEventListener(type, listener) { listeners.delete(listener); },
      animate(target = this) { [...listeners].forEach(listener => listener({ target })); },
      listeners,
    };
  }
  const song = node("song"), library = node("library");
  stage.append(song);
  const context = vm.createContext({ appStage: stage, closeQueue() {},
    matchMedia: () => ({ matches: reducedMotion }), contentScrollY: () => 50, window: { scrollY: 50 },
    document: { documentElement: { clientWidth: 390 } },
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
  });
  // Include the transition's owner declaration when present. The original
  // implementation has no owner, so this same harness reaches its actual race.
  const start = source.includes("  let finishViewTransition =")
    ? source.indexOf("  let finishViewTransition =") : source.indexOf("  const transitionTo =");
  vm.runInContext(source.slice(start, source.indexOf("  const route =", start)), context);
  const transition = vm.runInContext("transitionTo", context);
  const finishTimers = () => [...timers.values()].forEach(callback => callback());
  const settled = expected => {
    assert.deepEqual(stage.children.map(child => child.name), [expected]);
    assert.equal(stage.style.height, "");
    assert.equal(stage.classList.contains("is-view-transitioning"), false);
    assert.equal(timers.size, 0);
    for (const root of [song, library]) {
      assert.equal(root.listeners.size, 0);
      assert.equal(root.classList.values.size, 0);
    }
  };
  return { stage, song, library, transition, timers, finishTimers, settled };
}

(async () => {
  const reverse = setup();
  const first = reverse.transition(reverse.library, "right");
  const obsoleteTimer = [...reverse.timers.values()][0];
  const second = reverse.transition(reverse.song, "left");
  obsoleteTimer(); // A queued callback from the superseded animation is harmless.
  await first;
  reverse.finishTimers();
  await second;
  reverse.settled("song");

  // The arriving view slides in at the part it will open at: the departing
  // scroll (50) minus its own target, never parked out of sight at the top.
  const positioned = setup();
  const arriving = positioned.transition(positioned.library, "right");
  assert.equal(positioned.stage.style["--app-swipe-incoming-top"], "50px");
  assert.equal(positioned.stage.style["--app-swipe-scroll"], "50px", "departing song controls keep their place");
  positioned.finishTimers(); await arriving;
  assert.equal(positioned.stage.style["--app-swipe-incoming-top"], undefined);
  const returning = positioned.transition(positioned.song, "left", undefined, 345);
  assert.equal(positioned.stage.style["--app-swipe-incoming-top"], "-295px");
  assert.equal(positioned.stage.style["--app-swipe-scroll"], "345px", "arriving song controls use its own scroll");
  positioned.finishTimers(); await returning;
  positioned.settled("song");

  const repeated = setup();
  const incoming = repeated.transition(repeated.library, "right");
  await repeated.transition(repeated.library, "right");
  await incoming;
  repeated.settled("library");

  const rapid = setup();
  const requests = [rapid.transition(rapid.library, "right"),
    rapid.transition(rapid.song, "left"), rapid.transition(rapid.library, "right")];
  await Promise.resolve();
  assert.equal(rapid.stage.classList.contains("is-view-transitioning"), true,
    "Old promise continuations must not clear the active animation");
  assert.equal(rapid.stage.style.height, "100px");
  rapid.library.animate({}); // Descendant lyric animations do not end page motion.
  assert.equal(rapid.timers.size, 1);
  rapid.library.animate();
  await Promise.all(requests);
  rapid.settled("library");

  const reduced = setup({ reducedMotion: true });
  await reduced.transition(reduced.library, "right");
  await reduced.transition(reduced.song, "left");
  reduced.settled("song");
  console.log("View transition ownership and rapid navigation passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
