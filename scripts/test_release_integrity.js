#!/usr/bin/env node
'use strict';
// Inspect the actual assembled artifact, including every direct song entrypoint.
// These checks prove resource/content identity, not browser font/layout behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const site = path.join(root, '_site');
const pages = ['index.html', ...fs.readdirSync(path.join(root, 'songs'))
  .filter(slug => fs.existsSync(path.join(root, 'songs', slug, 'index.html')))
  .map(slug => `songs/${slug}/index.html`)];
let checked = 0;
for (const file of pages) {
  const original = new JSDOM(fs.readFileSync(path.join(root, file), 'utf8'));
  const deployed = new JSDOM(fs.readFileSync(path.join(site, file), 'utf8'));
  try {
    const source = original.window.document, doc = deployed.window.document;
    assert.equal(doc.title, source.title, `${file}: preserve title`);
    const sources = document => [...document.querySelectorAll('audio source')]
      .map(node => [node.getAttribute('src'), node.getAttribute('type')]);
    assert.deepEqual(sources(doc), sources(source), `${file}: audio sources unchanged`);
    assert.equal(doc.querySelectorAll('#songAudio').length, 1);
    for (const element of doc.querySelectorAll('script[src],link[rel="stylesheet"]')) {
      const value = element.getAttribute('src') || element.getAttribute('href');
      assert.ok(value.startsWith('/'), `${file}: local runtime asset`);
      const url = new URL(value, 'https://bhakti.eeshan.xyz');
      const bytes = fs.readFileSync(path.join(site, url.pathname));
      const hash = crypto.createHash('sha256').update(bytes);
      const hex = hash.digest('hex');
      assert.equal(url.searchParams.get('v'), hex, `${file}: revision ${value}`);
      assert.equal(element.getAttribute('integrity'),
        `sha256-${Buffer.from(hex, 'hex').toString('base64')}`, `${file}: SRI ${value}`);
      checked++;
    }
    if (file.startsWith('songs/')) {
      const data = path.join(path.dirname(file), 'data.js');
      assert.deepEqual(fs.readFileSync(path.join(site, data)), fs.readFileSync(path.join(root, data)), data);
    }
  } finally { original.window.close(); deployed.window.close(); }
}
assert.deepEqual(fs.readFileSync(path.join(site,'data/songs.js')), fs.readFileSync(path.join(root,'data/songs.js')));
assert.deepEqual(fs.readFileSync(path.join(site,'data/shuffle-profiles.js')), fs.readFileSync(path.join(root,'data/shuffle-profiles.js')));
for (const file of fs.readdirSync(path.join(site, 'assets/fonts')).filter(file => file.endsWith('.woff2'))) {
  assert.equal(fs.readFileSync(path.join(site, 'assets/fonts', file)).subarray(0,4).toString(), 'wOF2');
}
console.log(`Release integrity: ${pages.length} entrypoints, ${checked} exact resource revisions/SRI, original audio sources and all song data preserved`);
