#!/usr/bin/env node
"use strict";

// Catalogue-wide integration: real jsdom HTML parsing, the production renderer,
// DOM click dispatch and playback controller seek every occurrence to its stored
// start. Native media is the only behavioral seam. No acoustic/Safari claim.
// Supply jsdom through NODE_PATH; it is a test tool, never a production asset.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const root = path.resolve(process.argv[2] || path.join(__dirname, ".."));
const source = fs.readFileSync(path.join(root, "assets/song.js"), "utf8");
const catalogue = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, "data/songs.js"), "utf8"), catalogue);
const songs = catalogue.window.BHAKTI_SONGS;
assert.ok(songs.length > 0, "The published catalogue must not be empty");
assert.equal(new Set(songs.map(song => song.slug)).size, songs.length, "Unique catalogue slugs");

function setup(slug) {
  const dom = new JSDOM('<main><div id="songRoot"></div></main><audio id="songAudio"><source src="https://example.test/audio.m4a"></audio>', {
    url: `https://bhakti.eeshan.xyz/songs/${slug}/`, runScripts: "outside-only", pretendToBeVisual: true,
  });
  const { window } = dom;
  window.matchMedia = () => ({ matches: false });
  window.Element.prototype.scrollIntoView = function () {};
  // Prevent offscreen enrichment: every plain occurrence must remain seekable.
  window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  const audio = window.document.getElementById("songAudio");
  Object.defineProperties(audio, Object.fromEntries(Object.entries({
    paused: true, ended: false, readyState: 1, currentTime: -1, error: null,
  }).map(([name, value]) => [name, { value, writable: true, configurable: true }])));
  let playCalls = 0;
  audio.play = function () { playCalls++; this.paused = false; this.dispatchEvent(new window.Event("play")); };
  audio.pause = function () { this.paused = true; this.dispatchEvent(new window.Event("pause")); };
  audio.load = () => {};
  window.eval(fs.readFileSync(path.join(root, "songs", slug, "data.js"), "utf8"));
  window.eval(source);
  window.BHAKTI_READER.setSong(window.BHAKTI_READER.snapshotGlobals());
  return { dom, window, audio, playCalls: () => playCalls,
    playback: window.BHAKTI_READER.playback(audio) };
}

let occurrences = 0;
let returningOccurrences = 0;
let chunkedSongs = 0;
for (const { slug } of songs) {
  const app = setup(slug);
  try {
    const sequence = app.window.SONG_SEQUENCE;
    const timings = app.window.SONG_TIMINGS;
    const rows = [...app.window.document.querySelectorAll("article.line")];
    assert.equal(rows.length, sequence.length, `${slug}: every occurrence exists immediately`);
    assert.equal(timings.length, sequence.length, `${slug}: complete timing map`);
    if (app.window.document.querySelectorAll(".lyric-chunk").length > 1) chunkedSongs++;
    const seen = new Set();
    rows.forEach((row, i) => {
      const label = `${slug} occurrence ${i} (${sequence[i].ref})`;
      assert.equal(row.id, `ln-${i}-${sequence[i].ref}`, `${label}: occurrence identity`);
      const buttons = row.querySelectorAll(".line-seek");
      assert.equal(buttons.length, 1, `${label}: one seek button`);
      const expected = timings[i]?.start;
      assert.ok(Number.isFinite(expected) && expected >= 0, `${label}: finite stored start required`);
      assert.notEqual(row.getAttribute("data-start"), null, `${label}: absent start must not become zero`);
      assert.equal(Number(row.dataset.start), expected, `${label}: rendered start`);
      if (seen.has(sequence[i].ref)) returningOccurrences++;
      seen.add(sequence[i].ref);
      for (const ready of [true, false]) {
        app.playback.pause();
        app.audio.currentTime = -1;
        app.audio.readyState = ready ? 1 : 0;
        const before = app.playCalls();
        // Exercise the real SVG descendant target as well as the button itself.
        const target = ready ? buttons[0] : buttons[0].querySelector("path");
        target.dispatchEvent(new app.window.MouseEvent("click", { bubbles: true }));
        assert.equal(app.playCalls(), before + 1, `${label}: native play within click`);
        if (!ready) {
          assert.equal(app.audio.currentTime, -1, `${label}: defer seek until metadata`);
          app.audio.readyState = 1;
          app.audio.dispatchEvent(new app.window.Event("loadedmetadata"));
        }
        assert.equal(app.audio.currentTime, expected, `${label}: exact ${ready ? "ready" : "deferred"} seek`);
      }
      occurrences++;
    });
    const before = app.playCalls();
    rows[0].dispatchEvent(new app.window.MouseEvent("click", { bubbles: true }));
    assert.equal(app.playCalls(), before, `${slug}: ordinary lyric clicks do not seek`);
  } finally { app.dom.window.close(); }
}
console.log(`PASS: ${songs.length} songs, ${occurrences} occurrence buttons, ${returningOccurrences} returning-reference occurrences, ${chunkedSongs} chunked readers; ${occurrences * 2} exact ready/deferred DOM-click seeks. No acoustic or native Safari verification claimed.`);
