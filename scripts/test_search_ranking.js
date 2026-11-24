#!/usr/bin/env node
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm');
const {spawnSync}=require('node:child_process');
const {test,after}=require('node:test');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const code=fs.readFileSync(path.join(root,'assets/library.js'),'utf8');
const context={window:{},document:{getElementById:()=>null}};
vm.runInNewContext(fs.readFileSync(path.join(root,'data/songs.js'),'utf8'),context);
vm.runInNewContext(code,context);
const api=context.window.BHAKTI_SEARCH;
const song=(slug,fields={})=>({slug,title:'Unrelated',languageTags:[],subjectTags:[],...fields});
const find=(songs,query,lyricIndex,facets={})=>Array.from(api.filterSongs(songs,{query,lyricIndex,...facets}),s=>s.slug);

// These fixtures deliberately put poor matches first. Expected order follows
// the public requirement, not catalogue order, artist order or match frequency.
test('whole title, leading title phrase, interior phrase and word prefix precede other fields',()=>{
 const songs=[song('lyric'),song('tag',{subjectTags:['Pārvatī']}),song('alias',{searchAliases:['Parvati']}),
  song('credit',{singer:'Parvati'}),song('prefix',{title:'Pārvatīpati'}),song('interior',{title:'Jaya Pārvatī'}),
  song('leading',{title:'Pārvatī Devī Mahāmāyāvinī'}),song('whole',{title:'Pārvatī'})];
 assert.deepEqual(find(songs,'Parvati',{lyric:['parvati '.repeat(1000)]}),
  ['whole','leading','interior','prefix','credit','alias','tag','lyric']);
});

test('complete multiword title beats words combined across credits; partial title gets no bonus',()=>{
 const songs=[song('mixed',{title:'Parvati',singer:'Mercy'}),song('complete',{title:'Parvati grants mercy'})];
 assert.deepEqual(find(songs,'parvati mercy'),['complete','mixed']);
 assert.deepEqual(find(songs,'mercy parvati'),['complete','mixed']);
});

test('whole words precede token prefixes; compact covering windows and earlier matches break ties',()=>{
 const songs=[song('prefix',{title:'Parvatipati grants mercy'}),song('far',{title:'Parvati gives us all mercy'}),
 song('late',{title:'O Parvati grants mercy'}),song('near',{title:'Parvati grants mercy'})];
 assert.deepEqual(find(songs,'parvati mercy'),['near','late','far','prefix']);
});

test('all credited roles are searchable; field priority precedes lyric exactness',()=>{
 const songs=[song('lyrics'),song('tag',{subjectTags:['Parvati']}),song('subtitle',{subtitle:'Parvati'}),
 song('legacy',{title:'C',credit:'Parvati'}),song('ensemble',{title:'B',ensemble:'Parvati'}),song('composer',{title:'A',composer:'Parvati'})];
 assert.deepEqual(find(songs,'Parvati',{lyrics:['parvati']}),['composer','ensemble','legacy','subtitle','tag','lyrics']);
});

test('overlapping prefixes still recognize every word in a complete title',()=>{
 const songs=[song('credit-match',{singer:'Ram sweet Rama'}),song('title-match',{title:'Rama Ramayana'})];
 assert.deepEqual(find(songs,'ram rama'),['title-match','credit-match']);
});

test('individual fields precede combined metadata, then lyrics and mixed lyric evidence',()=>{
 const songs=[song('mixed-lyrics',{title:'Parvati'}),song('lyrics'),
 song('combined',{writer:'Parvati',singer:'Mercy'}),song('one-credit',{writer:'Parvati grants mercy'})];
 assert.deepEqual(find(songs,'parvati mercy',{'mixed-lyrics':['mercy'],lyrics:['parvati grants mercy']}),
  ['one-credit','combined','lyrics','mixed-lyrics']);
});

test('typo results retain title, credit, tag, lyric priority',()=>{
 const songs=[song('lyrics'),song('tag',{subjectTags:['Parvati']}),song('credit',{singer:'Parvati'}),
 song('title',{title:'Parvati'})];
 assert.deepEqual(find(songs,'parvti',{lyrics:['parvati']}),['title','credit','tag','lyrics']);
});

test('a real typo word beats an accidental interior substring',()=>{
 const songs=[song('fragment',{title:'take my krshnadamodaram'}),song('hand')];
 assert.deepEqual(find(songs,'take my hnad',{fragment:['take my krshnadamodaram'],hand:['take hold of my hand']}),['hand','fragment']);
});

test('equally relevant results use deterministic title/credit/slug ties and empty input preserves browse order',()=>{
 const songs=[song('z',{title:'Z Parvati'}),song('a',{title:'A Parvati'})];
 assert.deepEqual(find(songs,'Parvati'),['a','z']);
 assert.deepEqual(find([...songs].reverse(),'Parvati'),['a','z']);
 assert.deepEqual(find(songs,''),['z','a']);
 assert.deepEqual(find(songs,'  '),['z','a']);
});

const temp=fs.mkdtempSync(path.join(os.tmpdir(),'bhakti-ranking-'));
after(()=>fs.rmSync(temp,{recursive:true,force:true}));
const built=spawnSync('python3',[path.join(root,'scripts/build_search_index.py'),'--output',path.join(temp,'index.json')],{encoding:'utf8'});
assert.equal(built.status,0,built.stderr);
const lyrics=JSON.parse(fs.readFileSync(path.join(temp,'index.json'),'utf8')).songs;
const catalogue=context.window.BHAKTI_SONGS;

test('actual catalogue ranks the song named Parvati first, then Parvati Devi, before and after lyrics',()=>{
 for(const index of [null,lyrics])for(const q of ['Parvati','Pārvatī','parvati']) {
  assert.deepEqual(find(catalogue,q,index).slice(0,2),['parvati-hanuman-ansh','parvati-devi-mahamayavini'],q);
 }
 assert.equal(find(catalogue,'parvati devi',lyrics)[0],'parvati-devi-mahamayavini');
 assert.equal(find(catalogue,'parvti',lyrics)[0],'parvati-hanuman-ansh');
});

test('actual input/render path preserves title order after deferred lyrics, facets, focus, audio and clearing',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);
 const dom=new JSDOM('<main><input id="songSearch"><button id="filterToggle"></button><span id="filterCount"></span><div id="tagFilters"></div><div id="songList"></div></main><audio id="songAudio"></audio>',{runScripts:'outside-only',url:'https://bhakti.test/'});
 const w=dom.window;w.BHAKTI_SONGS=catalogue;w.fetch=()=>pending;w.eval(code);
 try{
  const main=w.document.querySelector('main'),input=w.document.querySelector('input'),ctl=w.BHAKTI_LIBRARY.mount(main);
  const before=Array.from(ctl.getVisibleSongs(),s=>s.slug),cards=[...main.querySelectorAll('.song-card')];
  const audio=w.document.querySelector('audio');audio.currentTime=42;
  const type=q=>{input.value=q;input.dispatchEvent(new w.Event('input',{bubbles:true}));};
  const shown=()=>[...main.querySelectorAll('.song-card:not([hidden])')].map(c=>c.dataset.songSlug);
  input.focus();type('Parvati');
  assert.deepEqual(shown().slice(0,2),['parvati-hanuman-ansh','parvati-devi-mahamayavini']);
  resolve({ok:true,json:async()=>({schemaVersion:1,songs:lyrics})});
  await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
  assert.deepEqual(shown().slice(0,2),['parvati-hanuman-ansh','parvati-devi-mahamayavini']);
  const facet=[...main.querySelectorAll('[data-kind="singer"]')].find(b=>b.dataset.tag==='Shruti Sadolikar');
  facet.click();assert.deepEqual(shown(),['parvati-devi-mahamayavini','aarti-kijiye-shailsuta-ki']);facet.click();input.focus();
  assert.equal(w.document.activeElement,input);assert.equal(audio.currentTime,42);
  assert.equal(w.document.querySelector('audio'),audio);assert.deepEqual(new Set(main.querySelectorAll('.song-card')),new Set(cards));
  type('');assert.deepEqual(shown(),before);
 }finally{dom.window.close();}
});
