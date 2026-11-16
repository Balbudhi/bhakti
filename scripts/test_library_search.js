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

const { matchesSearch, filterSongs } = context.window.BHAKTI_SEARCH;
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

// Query words may span fields and arrive in any order; all words must match.
// Aliases supply evidenced spelling variants without broad phonetic conflation.
const namdevSong = {
  slug: "tirtha-vitthal-kshetra-vitthal",
  title: "Tīrtha Viṭṭhal Kṣetra Viṭṭhal",
  writer: "Nāmadev",
  singer: "Bhimsen Joshi",
  languageTags: ["Marathi"],
  subjectTags: ["Viṭṭhal"],
  searchAliases: ["Namdev", "Vitthal"]
};
const gobindSong = {
  title: "Prabh Jū To Kah Lāj Hamārī",
  writer: "Gurū Gobind Siṅgh",
  singer: "Bhai Balwinder Singh Rangila",
  languageTags: ["Punjabi"],
  subjectTags: [],
  searchAliases: ["Guru Gobind Singh", "Guru Govind Singh", "Prabh Ju To Kah Laj Hamari"]
};
assert.equal(matchesSearch(namdevSong, "namdev bhimsen tirtha"), true);
assert.equal(matchesSearch(namdevSong, "tirtha Namdev BHIMSEN"), true);
assert.equal(matchesSearch(namdevSong, "  namdev, Marathi vitthal  "), true);
assert.equal(matchesSearch(namdevSong, "namdev bhimsen krishna"), false);
assert.equal(matchesSearch(namdevSong, "namdev rangila"), false);
assert.equal(matchesSearch(namdevSong, ""), true);
assert.equal(matchesSearch(namdevSong, "  "), true);
assert.equal(matchesSearch(gobindSong, "Guru Gobind Singh"), true);
assert.equal(matchesSearch(gobindSong, "Govind Hamari Rangila"), true);
assert.equal(matchesSearch(gobindSong, "Guru Gobind bhimsen"), false);
assert.equal(matchesSearch(gobindSong, "Nanak Hamari"), false);
assert.equal(matchesSearch({ title: "ਨਾਮਦੇਵ", writer: "नामदेव" }, "ਨਾਮਦੇਵ"), true);
assert.equal(matchesSearch({ title: "ਨਾਮਦੇਵ", writer: "नामदेव" }, "नामदेव"), true);
assert.deepEqual(Array.from(filterSongs([namdevSong, gobindSong], {
  languages: ["Marathi"], query: "bhimsen namdev tirtha"
}), item => item.slug), ["tirtha-vitthal-kshetra-vitthal"]);
assert.equal(filterSongs([namdevSong, gobindSong], {
  languages: ["Punjabi"], query: "bhimsen namdev tirtha"
}).length, 0);

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

// Exercise the generated catalogue, not just synthetic aliases: common English
// poet/artist names must find the actual recordings carrying those credits.
for (const [query, slug] of [
  ["Namdev", "mo-kau-tar-le-rama"],
  ["Guru Tegh Bahadur", "kahe-re-ban-khojan-jai"],
  ["Guru Angad Dev", "je-sau-chanda-ugveh"],
  ["Guru Arjun Dev", "tum-karo-daya-mere-sai"],
  ["Nanak Dev", "aakha-jeeva-visrai-mar-jaau"],
  ["Tulsi Das", "rudrashtakam-rameshbhai-oza"],
  ["Annamayya", "nanati-baduku"],
  ["MS Subbulakshmi", "nanati-baduku"],
  ["namdev bhimsen tirtha", "tirtha-vitthal-kshetra-vitthal"],
  ["Annamayya Subbulakshmi Baduku", "nanati-baduku"],
  ["Tegh Bahadur Harjinder Khojan", "kahe-re-ban-khojan-jai"],
]) {
  const recording = bySlug(slug);
  assert.ok(recording, `Catalogue recording exists: ${slug}`);
  assert.equal(matchesSearch(recording, query), true, `${query} finds ${slug}`);
}
assert.equal(matchesSearch(bySlug("nanati-baduku"), "Annamayya Bhimsen Baduku"), false);
assert.equal(matchesSearch(bySlug("kahe-re-ban-khojan-jai"), "Tegh Bahadur Namdev"), false);

// Broad keyword searches can match words in different credits. Poet filtering
// must still unite the six recordings under one canonical person, including a
// genuinely joint-poet recording, for both common English spellings.
const gobindSlugs = [
  "benti-chaupai", "deh-shiva-bar-mohe-hai", "jin-prem-kiyo",
  "mittar-pyare-nu", "prabh-ju-to-kah-laj-hamari", "re-man-aiso-kar-sanyasa",
];
for (const query of ["", "Guru Gobind Singh", "Guru Govind Singh"]) {
  const selected = filterSongs(context.window.BHAKTI_SONGS, {
    poets: ["Gurū Gobind Siṅgh"], query,
  });
  assert.deepEqual(Array.from(selected, entry => entry.slug).sort(), gobindSlugs,
    `Canonical Guru Gobind Singh filter with query: ${query}`);
}

// A full name already present in a field takes precedence over incidental
// words spread across unrelated credits (e.g. Sabh Gobind Hai + singer Singh).
for (const query of ["Guru Gobind Singh", "Guru Govind Singh", "Govind Singh"]) {
  assert.deepEqual(Array.from(filterSongs(context.window.BHAKTI_SONGS, { query }),
    entry => entry.slug).sort(), gobindSlugs, `Exact person search: ${query}`);
  assert.equal(filterSongs(context.window.BHAKTI_SONGS, {
    query, poets: ["Nāmadev"],
  }).length, 0, "A poet filter cannot turn an exact-name search into incidental matches");
}
assert.deepEqual(Array.from(filterSongs(context.window.BHAKTI_SONGS, {
  query: "namdev bhimsen tirtha",
}), entry => entry.slug), ["tirtha-vitthal-kshetra-vitthal"]);
assert.equal(filterSongs(context.window.BHAKTI_SONGS, {
  query: "namdev bhimsen tirtha", languages: ["Punjabi"],
}).length, 0);

const filtered = filterSongs([
  song,
  { ...song, slug: "other", title: "Other", languageTags: ["Hindi"], subjectTags: ["Kṛṣṇa"] },
  { ...song, slug: "third", title: "Third", languageTags: ["Kannada"], subjectTags: ["Kṛṣṇa"] },
], { languages: ["Kannada"], subjects: ["Śiva"], query: "Akkamahadevi" });
assert.deepEqual(filtered.map(item => item.slug), ["thanu-karagadavaralli"]);

process.stdout.write("library search aliases: ok\n");
