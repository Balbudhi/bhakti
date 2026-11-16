#!/usr/bin/env node
'use strict';
// Execute production dispatch/handlers with real Queue state. Controlled engine
// output checks routing and atomic adoption; algorithm quality has separate tests.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const Queue=require('../assets/queue.js');
const source=fs.readFileSync(require.resolve('../assets/app.js'),'utf8');
const songs=['a','b','c','d'].map((slug,i)=>({slug,queueId:String(i+1),audioSources:[]}));
const old=Queue.create({mode:'custom',items:[...songs,songs[1]],currentIndex:1,sessionId:'retained',repeat:'all'});
function setup({revision='r1',snapshotRevision='r1',schemaVersion=1,taxonomyVersion=1,engineMode='valid',snapshotPresent=true}={}) {
  const handlers={}, calls=[], selected=[], warnings=[];
  const snapshot={schemaVersion,taxonomyVersion,revision:snapshotRevision,profiles:{}};
  const window={BHAKTI_SHUFFLE_REVISION:revision,BHAKTI_SHUFFLE_PROFILES:snapshotPresent?snapshot:undefined,
    BHAKTI_SHUFFLE:{order(items,options){
      calls.push(options);
      if(engineMode==='throw') throw new Error('controlled failure');
      if(engineMode==='invalid') return {items:items.slice(1)};
      return {items:[...items.slice(0,options.fixedPrefix),...items.slice(options.fixedPrefix).reverse()]};
    }}};
  const context=vm.createContext({window,Queue,Math:Object.assign(Object.create(Math),{random:()=>0.25}),
    console:{warn:(...args)=>warnings.push(args)},queueState:old,currentSong:old.items[1],
    suppressQueueRowAction:false,view:'song',
    queueSheet:{hidden:false,addEventListener:(name,fn)=>{handlers['queue:'+name]=fn;}},
    document:{addEventListener:(name,fn)=>{handlers[name]=fn;}},
    newSessionId:()=> 'new',
    setQueueState(state){context.queueState=state;context.currentSong=state.items[state.currentIndex];},
    selectAudioSong(song){selected.push(song);},showSong:async()=>{},attemptPlay(){selected.push('play');},
  });
  const begin=source.indexOf('  const runShuffle =');
  const end=source.indexOf('  const pathSlug =',begin);
  assert.ok(begin>=0 && end>begin,'production shuffle dispatch exists');
  vm.runInContext(source.slice(begin,end),context);
  const libraryStart=source.indexOf('  document.addEventListener("bhakti:shuffle-request"');
  const libraryEnd=source.indexOf('  document.addEventListener("click"',libraryStart);
  vm.runInContext(source.slice(libraryStart,libraryEnd),context);
  const queueStart=source.indexOf('  queueSheet.addEventListener("click"');
  const queueEnd=source.indexOf('  queueSheet.addEventListener("keydown"',queueStart);
  vm.runInContext(source.slice(queueStart,queueEnd),context);
  return {context,calls,selected,warnings,
    library:()=>handlers['bhakti:shuffle-request']({detail:{songs}}),
    suffix:()=>handlers['queue:click']({target:{closest:()=>({disabled:false,dataset:{queueAction:'shuffle'},closest:()=>null})}})};
}
(async()=>{
  const fresh=setup();await fresh.library();
  assert.equal(fresh.calls.length,1);
  assert.equal(fresh.calls[0].fixedPrefix,0);
  assert.deepEqual(Array.from(fresh.context.queueState.items,s=>s.slug),['d','c','b','a']);
  assert.equal(fresh.context.queueState.repeat,'off');
  assert.equal(fresh.context.queueState.sessionId,'new');
  assert.equal(fresh.selected.at(-1),'play');
  const suffix=setup();suffix.suffix();
  assert.equal(suffix.calls[0].fixedPrefix,2);
  assert.deepEqual(suffix.context.queueState.items.slice(0,2),old.items.slice(0,2));
  assert.equal(suffix.context.currentSong.entryId,old.items[1].entryId);
  assert.equal(suffix.context.queueState.repeat,'all');
  assert.deepEqual(suffix.selected,[],'Suffix shuffle must never reset/select/play media');
  for(const config of [{revision:'new',snapshotRevision:'old'},{revision:'old',snapshotRevision:'new'},
    {schemaVersion:2},{taxonomyVersion:2},{revision:undefined,snapshotRevision:undefined},
    {revision:'',snapshotRevision:''},{snapshotPresent:false}]) {
    // Explicit missing revisions, not default destructuring values.
    const test=setup(config);
    if(config.revision===undefined && Object.hasOwn(config,'revision')) {
      test.context.window.BHAKTI_SHUFFLE_REVISION=undefined;
      test.context.window.BHAKTI_SHUFFLE_PROFILES.revision=undefined;
    }
    test.suffix();
    assert.equal(test.calls.length,0,'Missing/mismatched metadata must not reach optimizer');
    assert.deepEqual(test.context.queueState,Queue.shuffleRemaining(old,()=>0.25));
  }
  for(const engineMode of ['throw','invalid']) {
    const test=setup({engineMode});test.suffix();
    assert.equal(test.calls.length,1);
    assert.equal(test.warnings.length,1);
    assert.deepEqual(test.context.queueState,Queue.shuffleRemaining(old,()=>0.25));
    assert.deepEqual(test.selected,[]);
  }
  for (const engine of [undefined, {}]) {
    const test=setup();test.context.window.BHAKTI_SHUFFLE=engine;test.suffix();
    assert.equal(test.calls.length,0);
    assert.deepEqual(test.context.queueState,Queue.shuffleRemaining(old,()=>0.25));
  }
  console.log('shuffle app routing: matched metadata, fallback, exact queue and unchanged audio passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
