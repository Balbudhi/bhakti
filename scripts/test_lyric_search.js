#!/usr/bin/env node
'use strict';
// Actual generated index + DOM consumer: excludes unused words, preserves names,
// and exercises input/facet/async ordering without touching the listener audio.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {test, after} = require('node:test');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'bhakti-lyric-search-'));
after(() => fs.rmSync(fixture, {recursive:true, force:true}));
fs.mkdirSync(path.join(fixture, 'assets'), {recursive:true});
fs.mkdirSync(path.join(fixture, 'data'), {recursive:true});
fs.copyFileSync(path.join(root,'assets/library.js'), path.join(fixture,'assets/library.js'));
const catalogue = [
  {slug:'title', title:'Lotus', writer:'Guru Gobind Singh', searchAliases:['Feet protective'], singer:'Z', languageTags:['Hindi'], subjectTags:['Kṛṣṇa']},
  {slug:'lyrics', title:'Another song', writer:'Kabīr', singer:'A', languageTags:['Punjabi'], subjectTags:['Kṛṣṇa']},
  {slug:'incidental', title:'Third', writer:'Guru', singer:'Gobind Singh', languageTags:['Hindi'], subjectTags:[]},
];
function writeReader(slug, lines, sequence) {
  const directory = path.join(fixture, 'songs', slug); fs.mkdirSync(directory,{recursive:true});
  fs.writeFileSync(path.join(directory,'data.js'), `window.SONG_LINES=${JSON.stringify(lines)};window.SONG_SEQUENCE=${JSON.stringify(sequence)};`);
}
writeReader('title', {a:{source:'नाम', roman:'nām', english:'{0:My refuge}', words:[{roman:'nām',gloss:'name'}]}}, [{ref:'a',section:'verse'}]);
writeReader('lyrics', {
  a:{source:'कमल चरण',roman:'kamala caraṇa nām',english:'{0:Lotus }{1:feet}',words:[{roman:'caraṇa',gloss:'protective shelter'}]},
  b:{source:'मेरा हाथ पकड़ो',roman:'merā hātha pakaṛo',english:'Take hold of my hand',words:[{roman:'hātha',gloss:'hand'}]},
  hidden:{source:'Unperformedneedle',roman:'unused',english:'Unperformedneedle',words:[]},
  music:{source:'Instrumentalneedle',roman:'instrument',english:'Instrumentalneedle',words:[]},
}, [{ref:'a',section:'verse'},{ref:'a',section:'refrain'},{ref:'b',section:'verse'},{ref:'music',section:'instrumental'}]);
writeReader('incidental', {a:{source:'गुरु',roman:'guru',english:'Guru speaks of Gobind and Singh',words:[]}}, [{ref:'a',section:'verse'}]);
function build() {
  const result = spawnSync('python3',[path.join(root,'scripts/build_search_index.py'),'--root',fixture], {encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
  return JSON.parse(fs.readFileSync(path.join(fixture,'data/search-index.json'),'utf8'));
}
let index;
function mount(fetch) {
  const dom=new JSDOM('<main><input id="songSearch"><button id="filterToggle"></button><span id="filterCount"></span><div id="tagFilters"></div><div id="songList"></div></main><audio id="songAudio"></audio>',{runScripts:'outside-only',url:'https://bhakti.test/'});
  const w=dom.window;w.BHAKTI_SONGS=catalogue;w.BHAKTI_ASSETS={'/data/search-index.json':'/data/search-index.json?v=fixture'};w.fetch=fetch;
  w.eval(fs.readFileSync(path.join(root,'assets/library.js'),'utf8'));
  const main=w.document.querySelector('main'),search=w.document.querySelector('input'),controller=w.BHAKTI_LIBRARY.mount(main);
  const input=query=>{search.value=query;search.dispatchEvent(new w.Event('input',{bubbles:true}));};
  return {w,dom,search,main,controller,input,visible:()=>Array.from(controller.getVisibleSongs(),s=>s.slug)};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}

test('generated index covers performed layers and excludes unused/instrumental/private text',()=>{
  index=build(); assert.equal(index.schemaVersion,1);
  const app=mount(()=>{throw Error('not needed');});
  try {
    const find=query=>Array.from(app.w.BHAKTI_SEARCH.filterSongs(catalogue,{query,lyricIndex:index.songs}),s=>s.slug);
    for(const query of ['कमल चरण','kamala','caraṇa','carana','protective shelter']) assert.deepEqual(find(query),['lyrics'],query);
    assert.deepEqual(find('lotus'),['title','lyrics'],'title phrase ranks ahead of lyric match');
    assert.deepEqual(find('Guru Gobind Singh'),['title'],'scattered lyric or metadata words cannot forge an exact person phrase');
    assert.deepEqual(find('feet protective'),['title'],'a phrase cannot join English and a separate gloss');
    assert.deepEqual(find('unperformedneedle'),[]);assert.deepEqual(find('instrumentalneedle'),[]);
    assert.ok(!JSON.stringify(index).includes('{0:'));
  } finally {app.dom.window.close();}
});

test('index loads only on demand; completion uses latest query/facets and preserves DOM/focus/audio',async()=>{
  const pending=deferred(),calls=[];
  const app=mount(url=>{calls.push(url);return pending.promise;});
  try {
    const audio=app.w.document.getElementById('songAudio');audio.currentTime=47;
    const cards=[...app.main.querySelectorAll('.song-card')];app.search.focus();
    assert.equal(calls.length,0);
    app.input('shelter');await tick();assert.deepEqual(calls,['/data/search-index.json?v=fixture']);
    assert.equal(app.main.querySelector('.library-empty').hidden,false);
    assert.match(app.main.querySelector('.library-empty').textContent,/searching lyrics/i);
    app.input('lotus');
    const facet=app.main.querySelector('[data-kind="language"][data-tag="Punjabi"]');facet.click();app.search.focus();
    pending.resolve({ok:true,json:async()=>index});await tick();await tick();
    assert.deepEqual(app.visible(),['lyrics']);assert.equal(calls.length,1);
    assert.equal(app.w.document.activeElement,app.search);assert.equal(facet.getAttribute('aria-pressed'),'true');
    assert.deepEqual(new Set(app.main.querySelectorAll('.song-card')),new Set(cards));assert.equal(audio.currentTime,47);
    assert.equal(app.w.document.getElementById('songAudio'),audio);
    facet.click();
    assert.deepEqual([...app.main.querySelectorAll('.song-card:not([hidden])')].map(card=>card.dataset.songSlug),['title','lyrics'],'DOM follows title-before-lyrics ranking');
    const link=app.main.querySelector('[data-song-slug="lyrics"] a');link.focus();
    app.input('');assert.equal(app.w.document.activeElement,link,'moving a row preserves its focused link');
    app.input('कमल');await tick();assert.equal(calls.length,1,'successful payload is reused');
  }finally{app.dom.window.close();}
});

test('clearing a query during loading stays cleared',async()=>{
  const pending=deferred();const app=mount(()=>pending.promise);
  try{app.input('shelter');app.input('');pending.resolve({ok:true,json:async()=>index});await tick();await tick();assert.equal(app.visible().length,3);assert.equal(app.search.value,'');}
  finally{app.dom.window.close();}
});

test('fetch or malformed index failure retains metadata and retries on later input',async()=>{
  let attempts=0;const app=mount(async()=>{attempts++;if(attempts===1)throw Error('offline');if(attempts===2)return{ok:true,json:async()=>({schemaVersion:1,songs:{lyrics:[null]}})};if(attempts===3)return{ok:true,json:async()=>({schemaVersion:1,songs:{}})};return{ok:true,json:async()=>index};});
  try {
    app.input('lotus');await tick();await tick();assert.deepEqual(app.visible(),['title']);assert.equal(attempts,1);
    app.input('shelter');await tick();await tick();assert.deepEqual(app.visible(),[]);assert.match(app.main.querySelector('.library-empty').textContent,/lyrics.*unavailable/i);assert.equal(attempts,2);
    app.input('missingword');await tick();await tick();assert.deepEqual(app.visible(),[]);assert.equal(attempts,3);
    app.input('shelter');await tick();await tick();assert.deepEqual(app.visible(),['lyrics']);assert.equal(attempts,4);
  }finally{app.dom.window.close();}
});

test('fallback searches generated lyrics and glosses, with metadata ahead of lyric-only matches',()=>{
  const app=mount(()=>{throw Error('not needed');});
  try {
    const find=(query,songs=catalogue,lyrics=index.songs)=>Array.from(app.w.BHAKTI_SEARCH.filterSongs(songs,{query,lyricIndex:lyrics}),s=>s.slug);
    assert.deepEqual(find('take my hnad'),['lyrics'],'omitted words and an adjacent transposition');
    assert.deepEqual(find('naam'),['lyrics','title'],'both lyric-only vowel matches remain findable, with title-alphabetical ties');
    assert.deepEqual(find('kabir hnad'),['lyrics'],'remembered credit and lyric word may be combined');
    assert.deepEqual(find('कमल sheltr'),['lyrics'],'mixed native-script exact word and Latin typo');
    assert.deepEqual(find('किमल sheltr'),[],'mixed-script fallback must not approximate the native word');
    assert.deepEqual(find('take my hnad unicorn'),[],'all supplied terms remain required');
    const accidental=[{slug:'fragment',title:'Arati',languageTags:[],subjectTags:[]},{slug:'intended',title:'Rescue',languageTags:[],subjectTags:[]}];
    const fragments={fragment:['take my krshnadamodaram'],intended:['take hold of my hand']};
    assert.deepEqual(find('take my hnad',accidental,fragments),['intended','fragment'],'a useful typo match outranks an accidental internal substring');
    assert.deepEqual(find('take my hand',accidental,fragments),['intended'],'a genuine exact lyric result still suppresses approximations');

    const songs=[{slug:'lyric-only',title:'Different',languageTags:[],subjectTags:[]},{slug:'metadata',title:'Shelter',languageTags:[],subjectTags:[]}];
    assert.deepEqual(find('sheltr',songs,{'lyric-only':['shelter'],metadata:[]}),['metadata','lyric-only']);
  }finally{app.dom.window.close();}
});

test('pending lyrics use the latest typo query and keep filters, focus, and audio',async()=>{
  const pending=deferred();const app=mount(()=>pending.promise);
  try {
    const audio=app.w.document.getElementById('songAudio');audio.currentTime=29;
    const facet=app.main.querySelector('[data-kind="language"][data-tag="Punjabi"]');facet.click();
    app.input('lotuz');app.input('take my hnad');app.search.focus();
    pending.resolve({ok:true,json:async()=>index});await tick();await tick();
    assert.deepEqual(app.visible(),['lyrics']);assert.equal(app.w.document.activeElement,app.search);
    assert.equal(facet.getAttribute('aria-pressed'),'true');assert.equal(audio.currentTime,29);
    app.input('');assert.equal(app.search.value,'');assert.deepEqual(app.visible(),['lyrics']);
  }finally{app.dom.window.close();}
});

test('failed lyric loading preserves approximate metadata results and retries',async()=>{
  let attempts=0;const app=mount(async()=>{if(++attempts===1)throw Error('offline');return{ok:true,json:async()=>index};});
  try {
    app.input('lotuz');await tick();await tick();assert.deepEqual(app.visible(),['title']);
    app.input('take my hnad');await tick();await tick();assert.deepEqual(app.visible(),['lyrics']);assert.equal(attempts,2);
  }finally{app.dom.window.close();}
});

test('assembly regenerates search bytes and revisions them without eager precache',()=>{
  const result=spawnSync('python3',['-c',`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(path.join(root,'scripts'))});from assemble_public_site import assemble_public_site;r=Path(${JSON.stringify(fixture)});(r/'index.html').write_text('<html><head></head><body><script src="/assets/library.js"></script></body></html>');[(r/n).write_text('') for n in ('manifest.webmanifest','sw.js','robots.txt','sitemap.xml','CNAME')];(r/'data/songs.js').write_text('window.BHAKTI_SONGS=[];');[(p.parent/'index.html').write_text('<html><head></head><body></body></html>') for p in (r/'songs').glob('*/data.js')];(r/'data/search-index.json').write_text('stale');assemble_public_site(r)`],{encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
  const generated=JSON.parse(fs.readFileSync(path.join(fixture,'_site/data/search-index.json'),'utf8'));assert.ok(generated.songs.lyrics);
  const map=fs.readFileSync(path.join(fixture,'_site/assets/release-map.js'),'utf8');assert.match(map,/search-index\.json\?v=[a-f0-9]{64}/);
  const worker=fs.readFileSync(path.join(fixture,'_site/sw.js'),'utf8');const config=JSON.parse(worker.match(/^const BHAKTI_RELEASE = (.*);\n/)[1]);assert.ok(config.paths['/data/search-index.json']);assert.ok(!config.shell.some(url=>url.includes('search-index.json')));
});
