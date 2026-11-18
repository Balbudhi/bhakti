#!/usr/bin/env node
'use strict';
// Exercise the real worker/algorithm/profiles across a thread boundary. Controlled
// client events cover recovery and response races without wall-clock sleeps.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Worker} = require('node:worker_threads');
const root = path.resolve(__dirname, '..');
const engine = require('../assets/shuffle.js');
const profilesContext = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'data/shuffle-profiles.js'),'utf8'), profilesContext);
const bundle = profilesContext.window.BHAKTI_SHUFFLE_PROFILES;
const clientSource = () => fs.readFileSync(path.join(root,'assets/shuffle-client.js'),'utf8');
const assets = {'/assets/shuffle-worker.js':'/assets/shuffle-worker.js?v=release',
  '/assets/shuffle.js':'/assets/shuffle.js?v=release','/data/shuffle-profiles.js':'/data/shuffle-profiles.js?v=release'};
function setup(WorkerClass) {
  const timers = new Map(); let timerId = 0;
  const context = {window:{Worker:WorkerClass,BHAKTI_ASSETS:assets,location:{href:'https://example.org/'}},URL,
    setTimeout(fn,ms){timers.set(++timerId,{fn,ms});return timerId;},clearTimeout(id){timers.delete(id);}};
  vm.runInNewContext(clientSource(),context);
  return {api:context.window.BHAKTI_SHUFFLE_CLIENT,timers};
}
class FakeWorker {
  static created = [];
  constructor(url){this.url=url;this.messages=[];this.terminated=false;FakeWorker.created.push(this);}
  postMessage(value){this.messages.push(value);}
  terminate(){this.terminated=true;}
  respond(value){this.onmessage?.({data:value});}
}
class ThreadWorker {
  static created = [];
  constructor(url) {
    ThreadWorker.created.push(this);
    this.thread = new Worker(`const {parentPort,workerData}=require('node:worker_threads');
      const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
      globalThis.self=globalThis;
      globalThis.postMessage=value=>parentPort.postMessage(value);
      globalThis.importScripts=(...urls)=>urls.forEach(url=>vm.runInThisContext(fs.readFileSync(path.join(workerData.root,new URL(url).pathname),'utf8')));
      vm.runInThisContext(fs.readFileSync(path.join(workerData.root,'assets/shuffle-worker.js'),'utf8'));
      parentPort.on('message',data=>globalThis.onmessage({data}));`,{eval:true,workerData:{root}});
    this.thread.on('message',data=>this.onmessage?.({data}));
    this.thread.on('error',error=>this.onerror?.({message:error.message,preventDefault(){}}));
  }
  postMessage(value){this.thread.postMessage(value);}
  terminate(){this.thread.terminate();}
}
const options = {fixedPrefix:1,seed:12345,revision:bundle.revision};
const ids = Object.keys(bundle.profiles);
const items = [ids[0],ids[1],ids[0],...ids.slice(2,10)].map((queueId,i)=>({queueId,entryId:`occurrence-${i}`,title:`Song ${i}`}));
async function fakeTests() {
  await assert.rejects(setup(undefined).api.order(items,options),/Worker/);
  const test=setup(FakeWorker);
  assert.equal(FakeWorker.created.length,0,'startup must not construct a Worker or load profiles');
  const first=test.api.order(items,options);
  const worker=FakeWorker.created.at(-1);
  assert.equal(worker.url,'https://example.org/assets/shuffle-worker.js?v=release');
  assert.equal(worker.messages[0].engineUrl,'https://example.org/assets/shuffle.js?v=release');
  assert.equal(worker.messages[0].profilesUrl,'https://example.org/data/shuffle-profiles.js?v=release');
  const second=test.api.order(items,{...options,seed:7});
  const [one,two]=worker.messages;
  assert.notEqual(one.id,two.id);
  const forward=items.map((_,i)=>i),reverse=[0,...forward.slice(1).reverse()];
  worker.respond({id:two.id,indices:reverse});
  assert.equal((await second)[1],items.at(-1),'out-of-order replies must resolve the right request and original references');
  worker.respond({id:one.id,indices:forward});
  assert.equal((await first)[2],items[2]);
  assert.equal(test.timers.size,1,'only idle disposal remains');
  [...test.timers.values()][0].fn();
  assert.equal(worker.terminated,true,'idle worker releases profiles and thread');
  for(const indices of [[0,1],[...forward.slice(0,-1),0],[1,0,...forward.slice(2)],forward.map((x,i)=>i===2?1.5:x)]) {
    const promise=test.api.order(items,options);
    const current=FakeWorker.created.at(-1);
    current.respond({id:current.messages.at(-1).id,indices});
    await assert.rejects(promise,/invalid shuffle permutation/);
  }
  for(const event of ['onerror','onmessageerror']) {
    const promise=test.api.order(items,options),other=test.api.order(items,options);
    const current=FakeWorker.created.at(-1);
    current[event]({message:'broken worker',preventDefault(){}});
    await assert.rejects(promise); await assert.rejects(other);
    assert.equal(current.terminated,true);
  }
  const timed=test.api.order(items,options);
  const timeoutWorker=FakeWorker.created.at(-1);
  const timeout=[...test.timers.values()].find(timer=>timer.ms===15000);
  assert.ok(timeout); timeout.fn();
  await assert.rejects(timed,/timed out/);
  assert.equal(timeoutWorker.terminated,true);
  const controller=new AbortController();
  const cancelled=test.api.order(items,{...options,signal:controller.signal});
  const abortWorker=FakeWorker.created.at(-1);controller.abort();
  await assert.rejects(cancelled,error=>error.name==='AbortError');
  assert.equal(abortWorker.terminated,true);
  const count=FakeWorker.created.length;
  await assert.rejects(test.api.order(items,{...options,signal:controller.signal}),error=>error.name==='AbortError');
  assert.equal(FakeWorker.created.length,count,'already aborted requests load nothing');
  const disposed=test.api.order(items,options);test.api.dispose();
  await assert.rejects(disposed,/disposed/);
  // A late response from an old worker cannot settle a new request.
  const recovered=test.api.order(items,options),current=FakeWorker.created.at(-1);
  abortWorker.respond({id:current.messages[0].id,indices:reverse});
  current.respond({id:current.messages[0].id,indices:forward});
  assert.equal((await recovered)[1],items[1]);
  test.api.dispose();
}
function workerBoundaryTests() {
  const source=fs.readFileSync(path.join(root,'assets/shuffle-worker.js'),'utf8');
  for (const changed of [{schemaVersion:2},{taxonomyVersion:2},{revision:'stale'},{profiles:null}]) {
    const replies=[];
    const context={BHAKTI_SHUFFLE:engine,BHAKTI_SHUFFLE_PROFILES:{...bundle,...changed},
      importScripts(){},postMessage(value){replies.push(value);}};
    context.self=context;
    vm.runInNewContext(source,context);
    context.onmessage({data:{id:1,items,...options,engineUrl:'engine',profilesUrl:'profiles'}});
    assert.match(replies[0].error,/revision or schema/,'invalid profile snapshots must never produce an order');
    assert.equal(replies[0].indices,undefined);
  }
}
async function realTests() {
  const test=setup(ThreadWorker);
  try {
    const expected=engine.order(items,{...options,profiles:bundle.profiles}).items;
    const actual=await test.api.order(items,options);
    assert.deepEqual(Array.from(actual),expected,'worker preserves exact seeded algorithm results');
    actual.forEach(item=>assert.ok(items.includes(item),'result uses caller-owned occurrence references'));
    assert.equal(actual[0],items[0]);
    await assert.rejects(test.api.order(items,{...options,revision:'wrong'}),/revision/);
    for(const input of [[],[items[0]],items]) {
      const result=await test.api.order(input,{...options,fixedPrefix:input.length});
      assert.deepEqual(Array.from(result),input,'empty/singleton/all-fixed inputs remain intact');
    }
    const full=ids.map((queueId,i)=>({queueId,entryId:`full-${i}`}));
    const start=performance.now();
    const result=await test.api.order(full,options);
    assert.equal(result.length,ids.length);
    assert.equal(new Set(result).size,ids.length);
    console.log(`real worker: ${ids.length} songs, ${(performance.now()-start).toFixed(1)}ms round trip; all occurrences retained`);
  } finally {test.api.dispose();}
}
(async()=>{workerBoundaryTests();await fakeTests();await realTests();console.log('shuffle worker lifecycle, revision, identity and failure tests passed');})()
  .catch(error=>{console.error(error);process.exitCode=1;});
