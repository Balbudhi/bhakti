#!/usr/bin/env node
'use strict';
// Production handlers and Queue state, with deliberately delayed worker output.
// A gesture must play immediately; completion may reorder only its own queue.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const Queue=require('../assets/queue.js');
const engine=require('../assets/shuffle.js');
const source=fs.readFileSync(require.resolve('../assets/app.js'),'utf8');
const songs=['a','b','c','d'].map((slug,i)=>({slug,queueId:String(i+1),audioSources:[]}));
const old=Queue.create({mode:'custom',items:[...songs,songs[1]],currentIndex:1,sessionId:'retained',repeat:'all'});
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function setup({available=true,revision='r1'}={}) {
  const handlers={}, calls=[], selected=[], warnings=[];
  const window={BHAKTI_SHUFFLE_REVISION:revision,BHAKTI_SHUFFLE_CLIENT:available?{order(items,options){
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    calls.push({items,options,resolve,reject});return promise;
  }}:undefined};
  const context=vm.createContext({window,Queue,AbortController,Math:Object.assign(Object.create(Math),{random:()=>0.25}),
    console:{warn:(...args)=>warnings.push(args)},queueState:old,currentSong:old.items[1],
    suppressQueueRowAction:false,view:'song',systemMedia:null,
    queueSheet:{hidden:true,addEventListener:(name,fn)=>{handlers['queue:'+name]=fn;}},
    document:{addEventListener:(name,fn)=>{handlers[name]=fn;}},
    newSessionId:()=> 'new',persistQueue(){},renderQueuePill(){},updateViewToggle(){},replaceHistoryMarker(){},
    selectAudioSong(song){selected.push(song);},showSong:()=>new Promise(()=>{}),attemptPlay(){selected.push('play');},
    playback:{isPlaying:()=>true,isPending:()=>false,pause(){selected.push('pause');}},
  });
  const begin=source.indexOf('  let shuffleRequest =');
  assert.ok(begin>=0,'async shuffle request owner exists');
  vm.runInContext(source.slice(begin,source.indexOf('  const pathSlug =',begin)),context);
  vm.runInContext(source.slice(source.indexOf('  const setQueueState ='),source.indexOf('  const resolvedSources =')),context);
  const libraryStart=source.indexOf('  document.addEventListener("bhakti:shuffle-request"');
  vm.runInContext(source.slice(libraryStart,source.indexOf('  document.addEventListener("click"',libraryStart)),context);
  const queueStart=source.indexOf('  queueSheet.addEventListener("click"');
  vm.runInContext(source.slice(queueStart,source.indexOf('  queueSheet.addEventListener("keydown"',queueStart)),context);
  return {context,calls,selected,warnings,
    set:state=>{context.nextState=state;vm.runInContext('setQueueState(nextState)',context);},
    library:()=>handlers['bhakti:shuffle-request']({detail:{songs}}),
    action:action=>handlers['queue:click']({target:{closest:()=>({disabled:false,dataset:{queueAction:action},closest:()=>null})}})};
}
(async()=>{
  const fresh=setup();fresh.library();
  assert.equal(fresh.selected.at(-1),'play','play must occur before song data/navigation resolves');
  const baseline=fresh.context.queueState;
  await flush();assert.equal(fresh.calls.length,1);
  const request=fresh.calls[0];
  assert.equal(request.options.fixedPrefix,0);
  const exact=engine.order(request.items,{seed:request.options.seed,profiles:{}}).items;
  assert.equal(baseline.items[0].entryId,exact[0].entryId,'immediate starter matches exact seeded engine');
  request.resolve(exact);await flush();
  assert.deepEqual(fresh.context.queueState.items.map(x=>x.entryId),exact.map(x=>x.entryId));
  assert.equal(fresh.context.queueState.sessionId,'new');
  assert.equal(fresh.selected.filter(x=>x==='play').length,1,'worker completion must not replay or replace media');
  for(const mode of ['pause','repeat','edit','new-shuffle','bad-starter','invalid','failure']) {
    const test=setup();test.action('shuffle');await flush();
    const pending=test.calls[0],before=test.context.queueState;
    assert.equal(pending.options.fixedPrefix,2);
    assert.equal(before.items[1].entryId,old.items[1].entryId);
    assert.equal(before.repeat,'all');
    if(mode==='pause')test.action('queue-play');
    if(mode==='repeat')test.set(Queue.cycleRepeat(before));
    if(mode==='edit')test.set(Queue.append(before,{slug:'e',queueId:'e'}));
    if(mode==='new-shuffle'){test.action('shuffle');await flush();}
    const stateAfterAction=test.context.queueState;
    if(['repeat','edit','new-shuffle'].includes(mode))assert.equal(pending.options.signal.aborted,true);
    let result=[...pending.items.slice(0,2),...pending.items.slice(2).reverse()];
    if(mode==='bad-starter')[result[0],result[2]]=[result[2],result[0]];
    if(mode==='invalid')result=result.slice(1);
    if(mode==='failure')pending.reject(new Error('offline'));else pending.resolve(result);
    await flush();
    if(mode!=='pause')assert.equal(test.context.queueState,stateAfterAction,`${mode} cannot overwrite queue`);
    else assert.deepEqual(test.context.queueState.items.map(x=>x.entryId),result.map(x=>x.entryId));
    assert.deepEqual(test.selected,mode==='pause'?['pause']:[],'suffix shuffle never touches audio');
  }
  for(const config of [{available:false},{revision:''}]){
    const test=setup(config);test.action('shuffle');await flush();
    assert.equal(test.calls.length,0);assert.equal(test.context.queueState.items.length,old.items.length);
  }
  console.log('async shuffle: immediate play, exact starter, occurrence/prefix retention, failures and queue races passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
