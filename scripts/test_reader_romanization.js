#!/usr/bin/env node
"use strict";

// Contract: displayed romanization is IAST with plain e/o outside Tamil, Telugu,
// Kannada, Malayalam and Tulu lines, composed letters, and no mark spanning two
// letters. Stored readers are unchanged, every word keeps its link, and every
// displayed Latin character lies in the single EB Garamond face's range, so a
// letter and its marks never split between that font and a system one.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "assets/song.js"), "utf8");

const dom = new JSDOM('<main><div id="songRoot"></div></main><audio id="songAudio"></audio>',
  { url: "https://bhakti.eeshan.xyz/songs/x/", runScripts: "outside-only" });
const { window } = dom;
window.matchMedia = () => ({ matches: false });
window.eval(`${source}
  window.TEST = { displayRoman, displayLine, marksMacronEO, lineForEdition, renderRomanWithSpans };`);
const { displayRoman, displayLine, lineForEdition, renderRomanWithSpans } = window.TEST;

assert.equal(displayRoman("Kyō̃ paradēsī rahē̃", false), "Kyõ paradesī rahẽ");
assert.equal(displayRoman("Ō Ēk", false), "O Ek");
assert.equal(displayRoman("Kōḷaṟu", true), "Kōḷaṟu");
assert.equal(displayRoman("mẽ", true), "mẽ");
assert.equal(displayRoman("ha͠i", true), "haĩ");
assert.equal(displayRoman("k͟h", true), "ḵẖ");
assert.equal(displayRoman("jāū̃ hṛdayam̐ Sāīṁ", false), "jāū̃ hṛdayam̐ Sāīṁ");

const faces = [...fs.readFileSync(path.join(root, "assets/fonts.css"), "utf8")
  .matchAll(/font-family: '([^']+)'[\s\S]*?url\("([^"]+)"\)[\s\S]*?unicode-range: ([^;]+);/g)];
assert.equal(new Set(faces.map(face => face[2])).size, faces.length);
assert.equal(faces.filter(face => face[1] === "EB Garamond").length, 1, "one face per family and style");
for (const face of faces) assert.ok(fs.existsSync(path.join(root, face[2])), face[2]);
const ranges = faces.find(face => face[1] === "EB Garamond")[3].split(",").map(range => {
  const [low, high] = range.trim().slice(2).split("-");
  return [parseInt(low, 16), parseInt(high || low, 16)];
});
const covered = character => ranges.some(([low, high]) =>
  character.codePointAt(0) >= low && character.codePointAt(0) <= high);

const spans = html => (html.match(/data-word-i=/g) || []).length;
let lines = 0, changed = 0;
for (const slug of fs.readdirSync(path.join(root, "songs")).sort()) {
  const file = path.join(root, "songs", slug, "data.js");
  if (!fs.existsSync(file)) continue;
  for (const name of ["SONG_META", "SONG_LINES"]) delete window[name];
  window.eval(fs.readFileSync(file, "utf8"));
  const meta = window.SONG_META;
  const dravidian = (meta.languages || []).some(l => ["Tamil", "Telugu", "Kannada", "Malayalam", "Tulu"].includes(l));
  for (const [id, stored] of Object.entries(window.SONG_LINES)) {
    if (!stored.roman) continue;
    const before = JSON.stringify(stored);
    const line = lineForEdition(stored, id, meta);
    const shown = displayLine(stored, id, meta);
    assert.equal(JSON.stringify(stored), before, `${slug}/${id} mutated`);
    lines++;
    if (shown.roman !== line.roman) changed++;
    assert.equal(spans(renderRomanWithSpans(shown.roman, shown.words)),
      spans(renderRomanWithSpans(line.roman, line.words)), `${slug}/${id} lost a word link`);
    assert.equal(displayRoman(shown.roman), shown.roman, `${slug}/${id} not stable`);
    const code = line.sourceLanguage;
    if (code ? !["ta", "te", "kn", "ml", "tcy"].includes(code) : !dravidian) {
      assert.doesNotMatch(shown.roman, /[ēōĒŌ]/, `${slug}/${id}`);
    }
    assert.doesNotMatch(shown.roman, /[͟͠]/, `${slug}/${id}`);
    for (const character of shown.roman.match(/[\p{Script=Latin}\p{M}]/gu) || []) {
      assert.ok(covered(character), `${slug}/${id}: U+${character.codePointAt(0).toString(16)} is outside the reader face`);
    }
  }
}
assert.ok(lines > 8000 && changed > 500, `${lines} lines, ${changed} changed`);
console.log(`Reader romanization: ${lines} lines, ${changed} displayed in normalized form, every word link kept`);
