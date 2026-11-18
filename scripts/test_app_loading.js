#!/usr/bin/env node
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(require.resolve('../assets/app.js'),'utf8');
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function setup(){
  const dom=new JSDOM('<div class="app-stage"><main class="song-page"><div id="songRoot"><p>retained text</p></div></main></div>',{url:'https://bhakti.eeshan.xyz/songs/a/'});
  const {window}=dom, {document}=window;
  const library=document.createElement('main');library.className='library-page';
  const mounted=[],visibility=[],routes=[],fetches=[];
  let snapshot=null;
  window.BHAKTI_ASSETS={'/songs/a/data.js':'/songs/a/data.js?v='+'ab'.repeat(32)};
  window.scrollTo=({top})=>{window.scrollY=top;};window.scrollY=345;
  window.BHAKTI_READER={snapshotGlobals:()=>snapshot,setSong:data=>{mounted.push(data.meta.slug);document.getElementById('songRoot').textContent=data.meta.title;},setVisible:value=>visibility.push(value)};
  window.BHAKTI_LIBRARY={mount(){}};
  const context=vm.createContext({window,document,DOMParser:window.DOMParser,Promise,Map,console,URL,
    songDataCache:new Map(),pendingSongData:new Map(),dataLoadChain:Promise.resolve(),
    visibleSongSlug:'a',readerScrollY:345,view:'song',viewRequest:0,
    queueState:{items:[{slug:'a'}],currentIndex:0},currentSong:{slug:'a'},songRoot:document.querySelector('main'),libraryRoot:library,
    appStage:document.querySelector('.app-stage'),bySlug:new Map(['a','b','c','d','e','f'].map(slug=>[slug,{slug}])),
    songPath:slug=>`/songs/${slug}/`,assetPath:path=>window.BHAKTI_ASSETS[path]||path,
    fetchMain(url,selector){let resolve;const promise=new Promise(yes=>resolve=yes);fetches.push({url,selector,resolve});return promise;},
    closeQueue(){},matchMedia:()=>({matches:true}),route:(...args)=>routes.push(args),updateViewToggle(){},showStatus(){},
    playback:{isPlaying:()=>false,isPending:()=>false},Queue:{playNow:(_state,item)=>({items:[item],currentIndex:0})},
    setQueueState(state){context.queueState=state;context.currentSong=state.items[state.currentIndex];},selectAudioSong(){},
  });
  vm.runInContext(source.slice(source.indexOf('  const snapshotCurrentGlobals ='),source.indexOf('  const fetchMain =')),context);
  vm.runInContext(source.slice(source.indexOf('  let libraryRootLoad ='),source.indexOf('  const route =')),context);
  vm.runInContext(source.slice(source.indexOf('  const showLibrary ='),source.indexOf('  const addSongToPlaylist =')),context);
  const run=code=>vm.runInContext(code,context);
  return {dom,window,document,context,mounted,visibility,routes,fetches,run,
    complete(slug,fail=false){const script=document.head.querySelector('script');assert.ok(script,'serialized request exists');
      assert.ok(script.src.includes(`/songs/${slug}/data.js`));snapshot={meta:{title:`Title ${slug}`},lines:{},sequence:[],timings:[]};
      script.dispatchEvent(new window.Event(fail?'error':'load'));},
  };
}
(async()=>{
  const app=setup();try{
    const {run,context,document}=app;
    const first=run('loadSongData("a")'),duplicate=run('loadSongData("a")');
    assert.equal(first,duplicate,'in-flight callers share one request');await flush();
    assert.equal(document.head.querySelector('script').getAttribute('src'),'/songs/a/data.js?v='+'ab'.repeat(32));
    assert.equal(document.head.querySelector('script').integrity,'sha256-'+Buffer.from('ab'.repeat(32),'hex').toString('base64'),'dynamic song scripts verify build digest');
    app.complete('a');await first;assert.equal(document.head.querySelectorAll('script').length,0);
    for(const slug of ['b','c','d','e','f']){const result=run(`loadSongData("${slug}")`);await flush();app.complete(slug);await result;}
    assert.equal(context.songDataCache.size,4,'resident data is bounded');assert.ok(context.songDataCache.has('a'),'mounted reader stays pinned');
    assert.ok(!context.songDataCache.has('b'),'least recent nonvisible reader is evicted');
    const failed=run('loadSongData("b")');await flush();app.complete('b',true);await assert.rejects(failed);
    const retry=run('loadSongData("b")');await flush();app.complete('b');await retry;
    const node=document.getElementById('songRoot').firstChild;
    await run('showLibrary()');assert.equal(app.window.scrollY,0);assert.equal(app.visibility.at(-1),false);
    await run('showSong("a")');assert.equal(app.window.scrollY,345);assert.equal(document.getElementById('songRoot').firstChild,node);
    assert.deepEqual(app.mounted,[],'same reader returns without render');assert.equal(document.title,'Title a');assert.equal(app.visibility.at(-1),true);
    app.window.scrollY=456;await run('showSong("a")');assert.equal(app.window.scrollY,456,'same-song click retains scroll');
    // Slow old data must not overwrite a later return to library.
    const stale=run('showSong("c")');await flush();
    const library=run('showLibrary()');await library;app.complete('c');await stale;
    assert.equal(context.view,'library');assert.deepEqual(app.mounted,[]);assert.equal(app.visibility.at(-1),false);
    assert.equal(document.querySelector('.app-stage').firstElementChild.className,'library-page');
    context.songRoot=null;
    const rootA=run('ensureSongRoot("a")'),rootB=run('ensureSongRoot("b")');
    assert.equal(app.fetches.length,1,'concurrent navigation shares the song template fetch');
    const template=document.createElement('main');app.fetches[0].resolve(template);
    assert.equal(await rootA,template);assert.equal(await rootB,template);
    assert.equal(context.songRoot,template);
    console.log('app loading: versioned dedup, bounded/pinned LRU, retry, same-reader DOM/scroll and stale navigation passed');
  }finally{app.dom.window.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
