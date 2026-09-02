#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

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

console.log("Bhakti popup placement: protected linked words and bounded tooltip verified");
