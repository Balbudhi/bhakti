#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const context = {
  window: { BHAKTI_SONGS: [] },
  document: { getElementById: () => null }
};
vm.runInNewContext(
  fs.readFileSync(path.join(__dirname, "..", "data", "songs.js"), "utf8"),
  context
);
vm.runInNewContext(
  fs.readFileSync(path.join(__dirname, "..", "assets", "library.js"), "utf8"),
  context
);

const { matchesSearch } = context.window.BHAKTI_SEARCH;
const song = {
  slug: "thanu-karagadavaralli",
  title: "Tanu Karagadavaralli Puṣpavanolle",
  subtitle: "A Vachana by Akkamahādevī",
  credit: "Akkamahādevī · Sangeeta Katti Kulkarni",
  languageTags: ["Kannada"],
  subjectTags: ["Śiva"],
  searchAliases: []
};

assert.equal(matchesSearch(song, "akkamahadevi"), true);
assert.equal(matchesSearch(song, "pushpavanolle"), true);
assert.equal(matchesSearch(song, "thanu"), true);
assert.equal(matchesSearch({ ...song, subjectTags: ["Śirḍī Sāī"] }, "Shirdi Sai"), true);
assert.equal(matchesSearch({ ...song, searchAliases: ["Sangeetha Katti"] }, "Sangeetha"), true);
assert.equal(matchesSearch(song, "Krishna"), false);

const bySlug = slug => context.window.BHAKTI_SONGS.find(entry => entry.slug === slug);
assert.equal(matchesSearch(bySlug("ishwar-se-kuch-mangna-ho-to"), "Shirdi Sai"), true);
assert.equal(matchesSearch(bySlug("ishwar-se-kuch-mangna-ho-to"), "Ishwar"), true);
assert.equal(matchesSearch(bySlug("thanu-karagadavaralli"), "Akkamahadevi"), true);
assert.equal(matchesSearch(bySlug("thanu-karagadavaralli"), "Sangeeta Katti"), true);
assert.equal(matchesSearch(bySlug("jhoothe-jag-ne"), "Jhoothe"), true);
for (const slug of ["koi-hor-nahi", "jhoothe-jag-ne", "duniya-de-dukhan"]) {
  const vaishnoSong = bySlug(slug);
  assert.equal(vaishnoSong.subjectTags.includes("Śakti"), true);
  assert.equal(vaishnoSong.subjectTags.includes("Vaiṣṇo Devī"), true);
  assert.equal(matchesSearch(vaishnoSong, "Vaishno Devi"), true);
}

process.stdout.write("library search aliases: ok\n");
