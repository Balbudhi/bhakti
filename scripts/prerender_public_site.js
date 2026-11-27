#!/usr/bin/env node
'use strict';
// Build visible HTML from the same renderers used by the app. This runs only
// against the isolated public snapshot, before its release hashes are bound.
// No bot-specific content, private fields, browser network, or source writes.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const {JSDOM} = require('jsdom');

function prerenderPublicSite(root) {
  const homePath = path.join(root, 'index.html');
  let home = fs.readFileSync(homePath, 'utf8');
  const librarySlot = /(<div\b[^>]*\bid="songList"[^>]*>)(\s*)(<\/div>)/;
  if (librarySlot.test(home)) {
    const dom = new JSDOM(home, {runScripts: 'outside-only', url: 'https://bhakti.eeshan.xyz/'});
    try {
      const w = dom.window;
      w.eval(fs.readFileSync(path.join(root, 'data/songs.js'), 'utf8'));
      w.eval(fs.readFileSync(path.join(root, 'assets/library.js'), 'utf8'));
      if (!w.BHAKTI_LIBRARY.mount(w.document.querySelector('#libraryView'))) {
        throw Error('Cannot prerender the public library');
      }
      const content = w.document.getElementById('songList').innerHTML;
      home = home.replace(librarySlot, (_match, open, _empty, close) => open + content + close);
      fs.writeFileSync(homePath, home);
    } finally {dom.window.close();}
  }
  const songSlot = /(<section\b[^>]*\bid="songRoot"[^>]*>)(\s*)(<\/section>)/;
  let renderer;
  for (const slug of fs.readdirSync(path.join(root, 'songs')).sort()) {
    const page = path.join(root, 'songs', slug, 'index.html');
    if (!fs.existsSync(page)) continue;
    let html = fs.readFileSync(page, 'utf8');
    if (!songSlot.test(html)) continue;
    renderer ??= fs.readFileSync(path.join(root, 'assets/song.js'), 'utf8');
    // The pure render functions need no live DOM. Never invoke mount/playback.
    const context = vm.createContext({window: {}, document: {addEventListener() {}},
      location: {pathname: `/songs/${slug}/`}, localStorage: {getItem() {return null;}}});
    vm.runInContext(fs.readFileSync(path.join(root, 'songs', slug, 'data.js'), 'utf8'), context, {timeout: 1000});
    const data = context.window;
    if (!data.SONG_META || !data.SONG_LINES || !Array.isArray(data.SONG_SEQUENCE) || !Array.isArray(data.SONG_TIMINGS)) {
      throw Error(`Incomplete static reader: ${slug}`);
    }
    vm.runInContext(renderer, context, {timeout: 1000});
    // Keep default edition, normalized IAST, notices, names tables and every
    // performed occurrence. Rich word links are attached by the live reader.
    const content = vm.runInContext('renderLineRange(lineRenderContext(), 0, PAGE_SEQUENCE.length, false)', context, {timeout: 5000});
    html = html.replace(songSlot, (_match, open, _empty, close) => open + content + close);
    fs.writeFileSync(page, html);
  }
}

if (require.main === module) prerenderPublicSite(path.resolve(process.argv[2]));
module.exports = {prerenderPublicSite};
