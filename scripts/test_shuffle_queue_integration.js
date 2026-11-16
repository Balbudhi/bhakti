#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const Queue = require('../assets/queue.js');
const songs = ['a', 'b', 'c', 'd'].map((slug, i) => ({slug, queueId:String(i+1), title:slug, audioSources:[]}));
global.window = {BHAKTI_SONGS:songs};
const catalogue = new Map(songs.map(s => [s.queueId,s]));
const reverseTail = (items, fixedPrefix) => [...items.slice(0,fixedPrefix), ...items.slice(fixedPrefix).reverse()];
let calls = 0;
const fresh = Queue.shuffle(songs, () => 0.25, 'fresh', (items, prefix) => {
  calls++;
  assert.equal(prefix,0);
  assert.ok(Object.isFrozen(items));
  assert.equal(new Set(items.map(s => s.entryId)).size,4);
  return reverseTail(items,prefix);
});
assert.equal(calls,1,'The real shuffle entrypoint must invoke the ordering callback');
assert.deepEqual(fresh.items.map(s=>s.slug),['d','c','b','a']);
assert.equal(fresh.currentIndex,0);
assert.equal(fresh.repeat,'off');
assert.equal(fresh.shuffleAll,false,'New orders must not masquerade as legacy seeded shuffle');
const shared = Queue.decode(Queue.encode(fresh),catalogue,'received');
assert.deepEqual(shared.items.map(s=>s.queueId),fresh.items.map(s=>s.queueId));
const base = Queue.create({mode:'custom',items:[...songs,songs[2],songs[1]],currentIndex:1,sessionId:'before',repeat:'all'});
const before = JSON.stringify(base);
const after = Queue.shuffleRemaining(base,()=>0.25,reverseTail);
assert.equal(JSON.stringify(base),before,'No mutation of the adopted session');
assert.deepEqual(after.items.slice(0,2),base.items.slice(0,2));
assert.deepEqual(after.items.slice(2).map(s=>s.entryId),base.items.slice(2).reverse().map(s=>s.entryId));
assert.equal(after.currentIndex,base.currentIndex);
assert.equal(after.sessionId,base.sessionId);
assert.equal(after.repeat,'all');
assert.equal(after.items[1].entryId,base.items[1].entryId);
assert.deepEqual(Queue.restore(JSON.stringify(after),catalogue).items.map(s=>s.queueId),after.items.map(s=>s.queueId));
assert.deepEqual(Queue.decode(Queue.encode(after),catalogue,'recipient').items.map(s=>s.queueId),after.items.map(s=>s.queueId));
for (const invalid of [items=>items.slice(1), items=>[...items,items[0]], items=>items.map((s,i)=>i===2?items[3]:s), items=>items.map(s=>({...s})), items=>[...items].reverse(),()=>null]) {
  assert.throws(()=>Queue.shuffleRemaining(base,()=>0.25,invalid),/order|occurrence|prefix/);
  assert.equal(JSON.stringify(base),before);
}
assert.throws(()=>Queue.shuffle(songs,()=>0.25,'invalid',()=>songs),/order|occurrence/);
assert.equal(Queue.shuffle(songs,()=>0.25,'legacy').shuffleAll,true,'Legacy call retains seed decoder compatibility');
// Explicit intelligent order must fit the real catalogue's existing share format.
const fs=require('node:fs');
const vm=require('node:vm');
const live={window:{}};
vm.runInNewContext(fs.readFileSync(require.resolve('../data/songs.js'),'utf8'),live);
const fullCatalogue=Array.from(live.window.BHAKTI_SONGS);
global.window.BHAKTI_SONGS=fullCatalogue;
const full=Queue.shuffle(fullCatalogue,()=>0.25,'full',reverseTail);
const payload=Queue.encode(full);
assert.ok(payload && payload.length<=4096,'Full-catalogue explicit order remains shareable');
const fullDecoded=Queue.decode(payload,new Map(fullCatalogue.map(s=>[s.queueId,s])),'full-recipient');
assert.deepEqual(Array.from(fullDecoded.items,s=>s.queueId),Array.from(full.items,s=>s.queueId));
console.log('shuffle queue integration: passed');
