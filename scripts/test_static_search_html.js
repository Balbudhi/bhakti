#!/usr/bin/env node
'use strict';
// Search crawlers and readers without JS receive the same public catalogue and
// performed text as the interactive reader, without exposing private metadata.
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'bhakti-static-search-'));
(async () => {
let home, song;
try {
  for (const name of ['index.html','manifest.webmanifest','sw.js','robots.txt','sitemap.xml','CNAME','assets/library.js','assets/song.js']) {
    const target = path.join(fixture,name);fs.mkdirSync(path.dirname(target),{recursive:true});
    fs.copyFileSync(path.join(root,name),target);
  }
  fs.writeFileSync(path.join(fixture,'index.html'),fs.readFileSync(path.join(fixture,'index.html'),'utf8').replace(/<script[^>]+(?:shuffle-profiles|assets\/shuffle)\.js[^>]*><\/script>/g,''));
  fs.mkdirSync(path.join(fixture,'data'));fs.mkdirSync(path.join(fixture,'songs/example'),{recursive:true});
  fs.copyFileSync(path.join(root,'songs/nirguna-galiya/index.html'),path.join(fixture,'songs/example/index.html'));
  fs.writeFileSync(path.join(fixture,'songs/example/index.html'),fs.readFileSync(path.join(fixture,'songs/example/index.html'),'utf8').replace(/<script[^>]+(?:shuffle-profiles|assets\/shuffle)\.js[^>]*><\/script>/g,''));
  fs.writeFileSync(path.join(fixture,'data/songs.js'),'window.BHAKTI_SONGS='+JSON.stringify([
    {slug:'example',queueId:'example',title:'Example <song>',writer:'Kabīr',singer:'Singer',languageTags:['Hindi'],subjectTags:['Nirguṇa']},
    {slug:'other',queueId:'other',title:'Other song',writer:'Other poet',singer:'Other singer',languageTags:['French'],subjectTags:['Śiva']}
  ])+';');
  const reader = {SONG_META:{slug:'example',queueId:'example',title:'Example <song>',languages:['Hindi'],privateNote:'PrivateReviewNeedle',
      editionDefault:'reviewed',editionVariants:{reviewed:{lines:{a:{english:'{0:Our} {1:home} & shelter'}}},other:{lines:{a:{english:'AlternateEditionNeedle'}}}}},
    SONG_LINES:{a:{source:'हमारा घर',roman:'hamārā ghara',english:'LegacyTranslationNeedle',words:[{roman:'hamārā',gloss:'our'},{roman:'ghara',gloss:'home'}]},
      unused:{source:'UnperformedNeedle',roman:'unused',english:'unused'}},
    SONG_SEQUENCE:[{ref:'a',section:'refrain'},{ref:'a',section:'verse'}],SONG_TIMINGS:[{start:1},{start:4}]};
  const data = Object.entries(reader).map(([key,value])=>'window.'+key+'='+JSON.stringify(value)+';').join('\n');
  fs.writeFileSync(path.join(fixture,'songs/example/data.js'),data);
  fs.mkdirSync(path.join(fixture,'songs/other'));
  fs.copyFileSync(path.join(fixture,'songs/example/index.html'),path.join(fixture,'songs/other/index.html'));
  fs.writeFileSync(path.join(fixture,'songs/other/data.js'),data);
  const before=fs.readFileSync(path.join(fixture,'songs/example/index.html'),'utf8');
  const run=spawnSync('python3',['-c','import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from assemble_public_site import assemble_public_site;assemble_public_site(Path(sys.argv[2]))',path.join(root,'scripts'),fixture],{encoding:'utf8'});
  assert.equal(run.status,0,run.stderr);
  home=new JSDOM(fs.readFileSync(path.join(fixture,'_site/index.html'),'utf8'),
    {runScripts:'outside-only',url:'https://bhakti.eeshan.xyz/',pretendToBeVisual:true});
  assert.equal(home.window.document.querySelectorAll('#songList a[href="/songs/example/"]').length,1,'raw HTML must link every public song');
  assert.equal(home.window.document.querySelector('[data-song-slug="example"] .library-song-title').textContent,'Example <song>');
  assert.match(home.window.document.querySelector('[data-song-slug="example"] .credit').textContent,/By Kabīr · sung by Singer/);
  const html=fs.readFileSync(path.join(fixture,'_site/songs/example/index.html'),'utf8');
  song=new JSDOM(html,{runScripts:'outside-only',url:'https://bhakti.eeshan.xyz/songs/example/'});
  // Hydrate the actual prerendered catalogue, then drive real filters, search
  // and the app's delegated song navigation. Network/media are controlled at
  // their boundaries; the library, queue, app and reader implementations run.
  const h=home.window, doc=h.document;
  h.matchMedia=query=>({matches:query==='(prefers-reduced-motion: reduce)',addEventListener(){},removeEventListener(){}});
  h.scrollTo=()=>{};
  h.HTMLMediaElement.prototype.load=function(){};
  h.HTMLMediaElement.prototype.play=function(){return Promise.resolve();};
  h.HTMLMediaElement.prototype.pause=function(){};
  h.eval(fs.readFileSync(path.join(fixture,'data/songs.js'),'utf8'));
  h.eval(fs.readFileSync(path.join(root,'assets/library.js'),'utf8'));
  const main=doc.querySelector('#libraryView');
  const controller=h.BHAKTI_LIBRARY.mount(main);
  assert.equal(doc.querySelectorAll('.song-card').length,2,'mount replaces static cards without duplicating them');
  assert.equal(h.BHAKTI_LIBRARY.mount(main),controller,'repeated mount uses the same controller');
  const cards=[...doc.querySelectorAll('.song-card')];
  const visible=()=>[...controller.getVisibleSongs()].map(item=>item.slug);
  const search=doc.querySelector('#songSearch');
  const input=value=>{search.value=value;search.dispatchEvent(new h.Event('input',{bubbles:true}));};
  assert.deepEqual(new Set(visible()),new Set(['example','other']));
  doc.querySelector('[data-kind="language"][data-tag="Hindi"]').click();
  assert.deepEqual(visible(),['example'],'mounted filter selects the expected static catalogue entry');
  input('other');assert.deepEqual(visible(),[],'search intersects the selected facet');
  doc.querySelector('[data-kind="all-languages"]').click();
  assert.deepEqual(visible(),['other'],'resetting the facet retains the query');
  input('example');assert.deepEqual(visible(),['example']);
  assert.deepEqual(new Set(doc.querySelectorAll('.song-card')),new Set(cards),'filtering retains mounted card identities');
  const requests=[];
  h.fetch=async url=>{requests.push(String(url));return {ok:true,text:async()=>html,json:async()=>JSON.parse(fs.readFileSync(path.join(fixture,'_site/data/search-index.json'),'utf8'))};};
  const append=doc.head.append.bind(doc.head);
  doc.head.append=(...nodes)=>{append(...nodes);for(const node of nodes){if(node.tagName==='SCRIPT'&&node.src.includes('/songs/example/data.js')){h.eval(data);queueMicrotask(()=>node.dispatchEvent(new h.Event('load')));}}};
  h.eval(fs.readFileSync(path.join(root,'assets/queue.js'),'utf8'));
  h.eval(fs.readFileSync(path.join(root,'assets/song.js'),'utf8'));
  // jsdom cannot execute optional dynamic owner/visit imports; those imports
  // are outside this navigation contract and the app already catches failure.
  h.console.warn=()=>{};
  h.eval(fs.readFileSync(path.join(root,'assets/app.js'),'utf8'));
  const audio=doc.getElementById('songAudio');
  doc.querySelector('.song-card-link[href="/songs/example/"]').click();
  for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.location.pathname,'/songs/example/','selection uses the real app route');
  assert.equal(h.BHAKTI_APP.getQueue().items[0].slug,'example');
  assert.equal(doc.getElementById('songAudio'),audio,'selection keeps the persistent audio node');
  assert.equal(doc.querySelectorAll('#songRoot article.line').length,2,'selected prerendered reader is adopted once');
  assert.equal(doc.querySelector('.line-english').textContent,'Our home & shelter');
  assert.equal(requests.filter(url=>url==='/songs/example/').length,1,'one selection fetches one reader');
  await h.BHAKTI_APP.showLibrary();
  assert.equal(doc.querySelectorAll('.song-card').length,2,'returning to the library does not append duplicate cards');
  assert.deepEqual(visible(),['example'],'returning preserves the search');
  const w=song.window;
  assert.equal(w.document.querySelectorAll('#songRoot article.line').length,2,'every performed instance must exist before JS');
  assert.equal(w.document.querySelector('.line-source').textContent,'हमारा घर');
  assert.equal(w.document.querySelector('.line-roman').textContent,'hamārā ghara');
  assert.equal(w.document.querySelector('.line-english').textContent,'Our home & shelter');
  assert.equal(w.document.querySelector('#ln-1-a').dataset.start,'4');
  assert.ok(!html.includes('PrivateReviewNeedle')&&!html.includes('UnperformedNeedle')&&!html.includes('AlternateEditionNeedle')&&!html.includes('LegacyTranslationNeedle'));
  // The real reader replaces the static content and keeps its seek occurrences.
  w.matchMedia=()=>({matches:false});w.eval(data);w.eval(fs.readFileSync(path.join(root,'assets/song.js'),'utf8'));
  w.eval('render()');
  assert.equal(w.document.querySelectorAll('#songRoot article.line').length,2);
  assert.equal(w.document.querySelector('.line-english').textContent,'Our home & shelter');
  assert.equal(fs.readFileSync(path.join(fixture,'songs/example/data.js'),'utf8'),data,'source reader identity is unchanged');
  assert.equal(fs.readFileSync(path.join(fixture,'songs/example/index.html'),'utf8'),before,'source document is unchanged');
  console.log('Static search HTML: crawlable catalogue, complete performed text, safe escaping, real catalogue filters/search/navigation, reader adoption, unchanged sources');
} finally {
  home?.window.close();song?.window.close();
  fs.rmSync(fixture,{recursive:true,force:true});
}

})().catch(error=>{console.error(error);process.exitCode=1;});
