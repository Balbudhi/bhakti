#!/usr/bin/env node
"use strict";

// Catalogue-wide integration check: the real renderer (including lazy batches),
// delegated click handler and playback controller must seek to each occurrence's
// stored start, including returning refrains. This does not listen to recordings
// or emulate Safari's native media/DOM implementation. HTMLParser reads emitted
// markup independently; only metadata/gloss UI wiring and native media are seams.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");
const root = path.resolve(process.argv[2] || path.join(__dirname, ".."));
const source = fs.readFileSync(path.join(root, "assets/song.js"), "utf8");
const catalogue = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, "data/songs.js"), "utf8"), catalogue);
const songs = catalogue.window.BHAKTI_SONGS;
assert.ok(songs.length > 0, "The published catalogue must not be empty");
assert.equal(new Set(songs.map(song => song.slug)).size, songs.length, "Unique catalogue slugs");

function setup(slug) {
  const window = { addEventListener() {} };
  vm.runInNewContext(fs.readFileSync(path.join(root, "songs", slug, "data.js"), "utf8"), { window });
  const clicks = [];
  const listeners = new Map();
  let markup = "";
  let playCalls = 0;
  const audio = {
    paused: true, ended: false, readyState: 1, currentTime: -1, error: null,
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    dispatchEvent(event) {
      for (const fn of listeners.get(event.type) || []) fn(event);
      return !event.defaultPrevented;
    },
    emit(type) { this.dispatchEvent({ type, target: this }); },
    querySelectorAll() { return [{}]; },
    play() { playCalls++; this.paused = false; this.emit("play"); },
    pause() { this.paused = true; this.emit("pause"); },
    load() {},
  };
  const reader = {
    replaceChildren() { markup = ""; },
    insertAdjacentHTML(position, html) { markup += html; },
    append(node) { node.isConnected = true; },
  };
  const document = {
    getElementById(id) { return id === "songAudio" ? audio : id === "songRoot" ? reader : null; },
    querySelectorAll() { return []; },
    addEventListener(type, fn) { if (type === "click") clicks.push(fn); },
    createElement() {
      return {
        isConnected: false, setAttribute() {},
        insertAdjacentHTML(position, html) { markup += html; },
        remove() { this.isConnected = false; },
      };
    },
  };
  const context = vm.createContext({ window, document, CustomEvent, Promise,
    localStorage: { getItem() { return null; } }, location: { pathname: `/songs/${slug}/` } });
  vm.runInContext(source, context, { filename: "assets/song.js" });
  vm.runInContext(`renderSongMeta = () => {}; wireInteractions = () => {};
    render(); setupKaraoke(); ensureRenderedThrough(PAGE_SEQUENCE.length - 1);`, context);
  assert.equal(clicks.length, 1, `${slug}: one delegated lyric seek handler`);
  const click = target => clicks[0]({ target });
  return { window, audio, markup, click, playCalls: () => playCalls,
    playback: window.BHAKTI_READER.playback(audio) };
}

// A standard HTML parser, rather than a renderer-shaped regexp, derives the
// actual article/button relationships and attributes delivered to the handler.
const parser = String.raw`
import json, sys
from html.parser import HTMLParser
class Reader(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.article=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == 'article' and 'line' in attrs.get('class','').split():
            assert self.article is None, 'Nested lyric articles'
            self.article={'id':attrs.get('id'), 'start':attrs.get('data-start'), 'buttons':0}
            self.rows.append(self.article)
        if tag == 'button' and 'line-seek' in attrs.get('class','').split():
            assert self.article is not None, 'Seek button outside lyric article'
            self.article['buttons'] += 1
    def handle_endtag(self, tag):
        if tag == 'article': self.article=None
out=[]
for html in json.load(sys.stdin):
    reader=Reader(); reader.feed(html); reader.close(); out.append(reader.rows)
json.dump(out,sys.stdout)
`;
const apps = songs.map(song => setup(song.slug));
const rendered = JSON.parse(execFileSync("python3", ["-c", parser], {
  input: JSON.stringify(apps.map(app => app.markup)), maxBuffer: 128 * 1024 * 1024,
  encoding: "utf8",
}));
let occurrences = 0;
let returningOccurrences = 0;
let lazySongs = 0;
let missingTimings = 0;
for (let s = 0; s < songs.length; s++) {
  const { slug } = songs[s];
  const app = apps[s];
  const sequence = app.window.SONG_SEQUENCE;
  const timings = app.window.SONG_TIMINGS;
  const rows = rendered[s];
  assert.equal(rows.length, sequence.length, `${slug}: every occurrence rendered`);
  assert.equal(timings.length, sequence.length, `${slug}: complete timing map`);
  if (sequence.length > 180) lazySongs++;
  const seen = new Set();
  rows.forEach((row, i) => {
    const label = `${slug} occurrence ${i} (${sequence[i].ref})`;
    assert.equal(row.id, `ln-${i}-${sequence[i].ref}`, `${label}: occurrence identity`);
    assert.equal(row.buttons, 1, `${label}: one seek button`);
    const expected = timings[i]?.start;
    if (!Number.isFinite(expected)) missingTimings++;
    assert.ok(Number.isFinite(expected) && expected >= 0, `${label}: finite stored start required`);
    assert.notEqual(row.start, null, `${label}: missing data-start must not become zero`);
    assert.equal(Number(row.start), expected, `${label}: rendered start`);
    if (seen.has(sequence[i].ref)) returningOccurrences++;
    seen.add(sequence[i].ref);
    const article = { dataset: { start: row.start } };
    const button = { closest: selector => selector === ".line" ? article : null };
    const target = { closest: selector => selector === ".line-seek" ? button : null };
    for (const ready of [true, false]) {
      app.playback.pause();
      app.audio.currentTime = -1;
      app.audio.readyState = ready ? 1 : 0;
      const before = app.playCalls();
      app.click(target);
      assert.equal(app.playCalls(), before + 1, `${label}: native play within click`);
      if (!ready) {
        assert.equal(app.audio.currentTime, -1, `${label}: defer seek until metadata`);
        app.audio.readyState = 1;
        app.audio.emit("loadedmetadata");
      }
      assert.equal(app.audio.currentTime, expected, `${label}: exact ${ready ? "ready" : "deferred"} seek`);
    }
    occurrences++;
  });
  const before = app.playCalls();
  app.click({ closest: () => null });
  assert.equal(app.playCalls(), before, `${slug}: ordinary lyric/gloss clicks do not seek`);
}
assert.equal(missingTimings, 0);
console.log(`PASS: ${songs.length} songs, ${occurrences} occurrence buttons, ${returningOccurrences} returning-reference occurrences, ${lazySongs} lazy readers; ${occurrences * 2} exact ready/deferred seeks. No acoustic or native Safari verification claimed.`);
