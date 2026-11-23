#!/usr/bin/env node
"use strict";

// Real DOM/HTML parsing plus the production renderer and event handlers. jsdom
// is a development-only npm dependency; it is not shipped.
// These checks establish content, work bounds and lifecycle, not browser paint.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "assets/song.js"), "utf8");

function setup(slug = "sampurna-sundarakanda") {
  const dom = new JSDOM('<main><div id="songRoot"></div></main><audio id="songAudio"></audio>', {
    url: `https://bhakti.eeshan.xyz/songs/${slug}/`, runScripts: "outside-only", pretendToBeVisual: true,
  });
  const { window } = dom;
  const frames = new Map();
  const observers = [];
  let frameId = 0;
  window.requestAnimationFrame = callback => { frames.set(++frameId, callback); return frameId; };
  window.cancelAnimationFrame = id => frames.delete(id);
  window.matchMedia = () => ({ matches: false });
  window.Element.prototype.scrollIntoView = function () { this.wasScrolled = true; };
  window.IntersectionObserver = class {
    constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
    observe(node) { this.targets.add(node); }
    unobserve(node) { this.targets.delete(node); }
    disconnect() { this.targets.clear(); }
    reveal(node) { this.callback([{ target: node, isIntersecting: true }]); }
  };
  const audio = window.document.getElementById("songAudio");
  let time = 0, reads = 0, paused = true;
  Object.defineProperties(audio, {
    currentTime: { configurable: true, get() { reads++; return time; }, set(value) { time = value; } },
    paused: { configurable: true, get() { return paused; } },
    ended: { configurable: true, get() { return false; } },
  });
  window.eval(fs.readFileSync(path.join(root, "songs", slug, "data.js"), "utf8"));
  window.eval(source);
  const data = window.BHAKTI_READER.snapshotGlobals();
  window.BHAKTI_READER.setSong(data);
  const reader = window.document.getElementById("songRoot");
  return { dom, window, audio, reader, data, frames, observers,
    start(value) { time = value; paused = false; audio.dispatchEvent(new window.Event("playing")); },
    time(value) { time = value; reads = 0; },
    reads: () => reads,
    frame() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn()); },
    ensure(index) { window.eval(`ensureRenderedThrough(${index})`); },
  };
}

let failed = 0;
function check(name, run) {
  try { run(); console.log(`PASS ${name}`); }
  catch (error) { failed++; console.error(`FAIL ${name}: ${error.stack}`); }
}

for (const slug of ["sampurna-sundarakanda", "vishnu-sahasranama"]) {
  check(`${slug}: complete searchable text, bounded rich markup and direct late seek`, () => {
    const app = setup(slug);
    try {
      const { window, reader, data } = app;
      const articles = [...reader.querySelectorAll("article.line")];
      assert.equal(articles.length, data.sequence.length, "Every occurrence exists immediately for find/accessibility");
      articles.forEach((article, index) => {
        const line = data.lines[data.sequence[index].ref];
        assert.equal(article.id, `ln-${index}-${data.sequence[index].ref}`);
        assert.equal(Number(article.dataset.start), data.timings[index].start);
        assert.equal(article.querySelectorAll(".line-seek").length, 1);
        if (line.nameTable && line.words.every(word => word.deva)) {
          const rows = [...article.querySelectorAll(".name-table-row")];
          assert.equal(rows.length, line.words.length);
          rows.forEach((row, i) => assert.deepEqual([...row.querySelectorAll(".name-table-cell")].map(cell => cell.textContent),
            [line.words[i].deva, line.words[i].citationRoman || line.words[i].roman || "", line.words[i].gloss || ""]));
        } else {
          if (line.source) assert.equal(article.querySelector(".line-source").textContent, line.source);
          assert.ok(article.querySelector(".line-roman").textContent.startsWith(window.eval("displayRoman")(line.roman, false)));
          assert.equal(article.querySelector(".line-english").textContent,
            line.english.replace(/\{[\d,\s]+:([^}]*)\}/g, "$1"));
        }
      });
      if (slug === "vishnu-sahasranama") {
        assert.equal(reader.querySelectorAll('.name-table-meaning [data-gloss]').length, 0,
          "Visible name meanings must not open redundant tooltips");
      }
      assert.ok(reader.querySelectorAll(".word-link").length <= 600, "Initial rich words have a content budget, including name tables");
      const first = articles[0];
      const last = articles.at(-1);
      const button = last.querySelector(".line-seek");
      app.ensure(articles.length - 1);
      assert.strictEqual(reader.querySelector("article.line"), first);
      assert.strictEqual(last.querySelector(".line-seek"), button, "Hydration preserves permanent occurrence controls");
      assert.ok(last.querySelectorAll(".word-link").length > 0, "The late seek target has working glosses");
      assert.ok(reader.querySelectorAll(".word-link").length <= 1200, "Late seek hydrates its chunk, not its entire prefix");
      const lastWord = last.querySelector(".word-link[data-gloss]");
      lastWord.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      assert.equal(window.document.querySelector(".word-tooltip").textContent, lastWord.dataset.gloss);
    } finally { app.dom.window.close(); }
  });
}

check("Reopening the identical song keeps DOM, selection and seek-button identity", () => {
  const app = setup("hanuman-chalisa");
  try {
    const first = app.reader.firstElementChild;
    const button = app.reader.querySelector(".line-seek");
    button.focus();
    app.window.BHAKTI_READER.setSong(app.data);
    assert.strictEqual(app.reader.firstElementChild, first);
    assert.strictEqual(app.window.document.activeElement, button);
  } finally { app.dom.window.close(); }
});

check("Hidden and detached readers stop clocks; resume updates correct occurrence once", () => {
  const app = setup();
  try {
    const { window, audio, data, reader } = app;
    app.start(data.timings[10].start);
    assert.equal(app.frames.size, 1);
    window.BHAKTI_READER.setVisible(false);
    assert.equal(app.frames.size, 0, "Hiding cancels queued RAF");
    app.time(data.timings.at(-1).start);
    audio.dispatchEvent(new window.Event("timeupdate"));
    assert.equal(app.reads(), 0, "Hidden reader does no timing lookup");
    window.BHAKTI_READER.setVisible(true);
    assert.equal(app.frames.size, 1);
    assert.equal(reader.querySelector(".is-singing").id, `ln-${data.sequence.length - 1}-${data.sequence.at(-1).ref}`);
    app.time(data.timings.at(-1).start + .01);
    app.frame();
    assert.equal(app.reads(), 1, "One native media time read per frame");
    reader.parentElement.remove();
    app.frame();
    assert.equal(app.frames.size, 0, "Detached roots cannot keep reader clocks alive");
  } finally { app.dom.window.close(); }
});

check("Timing lookup preserves exact first syllables, gaps and exclusive ends", () => {
  const app = setup("hanuman-chalisa");
  try {
    const { window, audio, data, reader } = app;
    for (const timing of data.timings) {
      for (const time of [timing.start - .001, timing.start, timing.end - .001, timing.end]) {
        app.time(time);
        audio.dispatchEvent(new window.Event("seeking"));
        const expected = data.timings.findIndex(segment => time >= segment.start && time < segment.end);
        const selected = reader.querySelector(".is-singing");
        assert.equal(selected?.id || "", expected < 0 ? "" : `ln-${expected}-${data.sequence[expected].ref}`);
      }
    }
  } finally { app.dom.window.close(); }
});

check("Logarithmic lookup preserves first-match semantics across every stored interval and nested overlaps", () => {
  const app = setup("hanuman-chalisa");
  try {
    const lookup = app.window.eval("activeTimingIndex");
    const catalogue = { window: {} };
    vm.runInNewContext(fs.readFileSync(path.join(root, "data/songs.js"), "utf8"), catalogue);
    const sets = catalogue.window.BHAKTI_SONGS.map(song => {
      const data = { window: {} };
      vm.runInNewContext(fs.readFileSync(path.join(root, "songs", song.slug, "data.js"), "utf8"), data);
      return { name: song.slug, timings: data.window.SONG_TIMINGS };
    });
    sets.push({ name: "nested and overlapping intervals", timings: [
      { start: 1, end: 20 }, { start: 5, end: 6 }, { start: 19, end: 30 }, { start: 40, end: 42 },
    ] });
    for (const { name, timings } of sets) {
      for (const segment of timings) {
        for (const time of [segment.start - .001, segment.start, (segment.start + segment.end) / 2, segment.end]) {
          const expected = timings.findIndex(value => time >= value.start && time < value.end);
          assert.equal(lookup(timings, time), expected, `${name} at ${time}`);
        }
      }
    }
  } finally { app.dom.window.close(); }
});

check("Scrolling without an open meaning does no reader-wide highlight scan", () => {
  const app = setup();
  try {
    const query = app.reader.querySelectorAll.bind(app.reader);
    let scans = 0;
    app.reader.querySelectorAll = selector => { scans++; return query(selector); };
    app.window.dispatchEvent(new app.window.Event("scroll"));
    assert.equal(scans, 0);
    const word = query(".word-link[data-gloss]")[0];
    word.dispatchEvent(new app.window.MouseEvent("click", { bubbles: true }));
    app.window.dispatchEvent(new app.window.Event("scroll"));
    assert.equal(scans, 1);
    assert.equal(query(".word-link.is-hi").length, 0);
    app.window.dispatchEvent(new app.window.Event("scroll"));
    assert.equal(scans, 1);
  } finally { app.dom.window.close(); }
});

check("Offscreen enhancement retains selected text and keyboard focus", () => {
  const app = setup();
  try {
    const { window, reader } = app;
    const article = reader.querySelectorAll("article.line")[100];
    const layer = article.querySelector(".line-roman");
    const range = window.document.createRange();
    range.selectNodeContents(layer);
    const selection = window.getSelection();
    selection.addRange(range);
    const original = selection.toString();
    const chunk = article.closest(".lyric-chunk");
    assert.ok(chunk, "Heavy readers are partitioned by content complexity");
    for (const observer of app.observers) observer.reveal(chunk);
    assert.equal(selection.toString(), original);
    selection.removeAllRanges();
    const button = article.querySelector(".line-seek");
    button.focus();
    assert.strictEqual(window.document.activeElement, button);
    assert.ok(article.querySelector(".word-link"), "Entering an unhydrated chunk by keyboard exposes its gloss controls");
  } finally { app.dom.window.close(); }
});

process.exitCode = failed ? 1 : 0;
