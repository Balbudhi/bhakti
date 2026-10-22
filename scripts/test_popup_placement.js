#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const song = fs.readFileSync(path.join(root, "assets/song.js"), "utf8");
const style = fs.readFileSync(path.join(root, "assets/song.css"), "utf8");

if (!song.includes("highlightedWordRects")
    || !song.includes('line.querySelectorAll(".word-link.is-hi")')
    || !song.includes("!overlapsProtected(candidate)")) {
  throw new Error("song tooltips must avoid every highlighted script, IAST, and English instance");
}

if (!style.includes("max-height: min(40dvh, 280px)")
    || !style.includes("overflow-y: auto")
    || !style.includes("overscroll-behavior: contain")) {
  throw new Error("song tooltips must remain bounded popup surfaces");
}

function placedPopup(playerRect) {
  const context = vm.createContext({
    window: { innerHeight: 390, scrollX: 0, scrollY: 0 },
    document: {
      documentElement: { clientWidth: 844 },
      getElementById: () => ({ getBoundingClientRect: () => ({ top: 0 }) }),
      querySelector: () => playerRect ? { getBoundingClientRect: () => playerRect } : null,
    },
    highlightedWordRects: () => [{ left: 10, right: 834, top: 110, bottom: 230 }],
  });
  vm.runInContext(song.slice(song.indexOf("function placeTooltip("), song.indexOf("function showTooltip(")), context);
  const tip = { style: {}, getBoundingClientRect() {
    return { width: 340, height: this.style.maxHeight ? Number.parseFloat(this.style.maxHeight) : 143 };
  } };
  context.placeTooltip(tip, { getBoundingClientRect: () => ({ left: 300, right: 500, top: 110, bottom: 230, width: 200, height: 120 }) });
  return { top: Number.parseFloat(tip.style.top), height: tip.getBoundingClientRect().height };
}

const abovePlayer = placedPopup({ top: 328, bottom: 390, width: 844, height: 62 });
assert.ok(abovePlayer.top >= 8);
assert.ok(abovePlayer.top + abovePlayer.height <= 320, "popup must stop eight pixels above the visible fixed player");
for (const player of [null, { top: 0, bottom: 0, width: 0, height: 0 }, { top: 400, bottom: 462, width: 844, height: 62 }]) {
  const popup = placedPopup(player);
  assert.equal(popup.top, 238, "absent, hidden, or offscreen player must not reduce available space");
  assert.equal(popup.height, 143);
}

console.log("Bhakti popup placement: protected linked words and bounded tooltip verified");
