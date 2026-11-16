#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const Shuffle = require('../assets/shuffle.js');
const item = (id, queueId = id) => Object.freeze({entryId:id,queueId,slug:id});
const items = Object.freeze(Array.from({length:8},(_,i)=>item(String(i))));
const ids = xs => xs.map(x=>x.entryId).join(',');
const algorithms = ['random','ils','mmas'];
const options = {seed:123, budget:{constructions:8,localProposals:96}};
function conserved(input, output, prefix=0) {
  assert.equal(output.length,input.length);
  const counts = new Map();
  input.forEach(x=>counts.set(x,(counts.get(x)||0)+1));
  output.forEach(x=>{assert.ok(counts.get(x)>0,'unexpected or excess occurrence'); counts.set(x,counts.get(x)-1);});
  assert.ok([...counts.values()].every(n=>n===0));
  for(let i=0;i<prefix;i++) assert.equal(output[i],input[i]);
}
function* permutations(xs) {
  if(!xs.length) {yield [];return;}
  for(let i=0;i<xs.length;i++) for(const rest of permutations(xs.filter((_,j)=>j!==i))) yield [xs[i],...rest];
}
function oracle(input,prefix,evaluate) {
  let best=Infinity;
  for(const suffix of permutations(input.slice(prefix))) best=Math.min(best,evaluate([...input.slice(0,prefix),...suffix]));
  return best;
}
for(const algorithm of algorithms) {
  for(const input of [[],[items[0]],items,[items[0],items[1],items[0],item('repeat','0')]]) {
    for(const fixedPrefix of [0,input.length,Math.min(2,input.length)]) {
      const cfg={...options,algorithm,fixedPrefix};
      const result=Shuffle.order(input,cfg);
      conserved(input,result.items,fixedPrefix);
      assert.equal(Number.isFinite(result.score),true);
      assert.deepEqual(result,Shuffle.order(input,cfg),'seeded replay includes work counters');
      assert.ok(result.stats.localProposals<=96);
      assert.ok(result.stats.constructions<=8);
      assert.ok(result.score<=result.baselineScore+1e-9);
    }
  }
  const orders=new Set(Array.from({length:12},(_,seed)=>ids(Shuffle.order(items,{...options,algorithm,seed}).items)));
  assert.ok(orders.size>=6,'uninformative profiles must preserve meaningful seed variation');
  const zero=Shuffle.order(items,{algorithm,seed:123,budget:{constructions:0,localProposals:0}});
  assert.equal(zero.stats.constructions,0);
  assert.equal(zero.stats.localProposals,0);
  assert.equal(zero.score,zero.baselineScore);
}
for(const fixedPrefix of [-1,1.5,9]) assert.throws(()=>Shuffle.order(items,{fixedPrefix}),/prefix/i);
for(const seed of [-1,NaN,2**32,1.5]) assert.throws(()=>Shuffle.order(items,{seed}),/seed/i);
assert.throws(()=>Shuffle.order(items,{algorithm:'unknown'}),/algorithm/i);
assert.throws(()=>Shuffle.order(items,{budget:{constructions:-1,localProposals:1}}),/budget/i);
assert.throws(()=>Shuffle.order(items,{budget:{constructions:65,localProposals:1}}),/budget/i);
assert.throws(()=>Shuffle.order(items,{transitionCost:()=>NaN}),/finite/i);

// Missing evidence is exactly neutral, including malformed acoustic values.
assert.equal(Shuffle.score(items),0);
assert.equal(Shuffle.score(items,{profiles:{'0':{semantic:{status:'accepted',themes:[{id:'longing',weight:1}]},audio:{status:'accepted',physical:{whole:{rmsDbfs:NaN,centroidHz:-2}}}}}}),0);
const malformed=Object.freeze({'0':Object.freeze({audio:Object.freeze({energy:NaN,tempo:2})})});
assert.equal(Shuffle.score(items,{profiles:malformed}),0);
const semantic=id=>({semantic:{status:'accepted',themes:[{id,weight:1}],actions:[],subjects:[]}});
const related={'0':semantic('longing'),'1':semantic('longing'),'2':semantic('service')};
assert.ok(Shuffle.score(items.slice(0,2),{profiles:related})<Shuffle.score([items[0],items[2]],{profiles:related}));

// Physical boundary evidence is directed; unaccepted measurements stay neutral.
const acoustic={
  '0':{audio:{status:'accepted',physical:{profiles:{beginning:{rmsDbfs:-10},end:{rmsDbfs:-10}}}}},
  '1':{audio:{status:'accepted',physical:{profiles:{beginning:{rmsDbfs:-10},end:{rmsDbfs:-50}}}}},
};
assert.ok(Shuffle.score([items[0],items[1]],{profiles:acoustic})<Shuffle.score([items[1],items[0]],{profiles:acoustic}));
const unknownAudio={'0':acoustic['0'],'1':{audio:{...acoustic['1'].audio,status:'unavailable'}}};
assert.equal(Shuffle.score([items[0],items[1]],{profiles:unknownAudio}),0);

const positivePeak={'0':{audio:{status:'accepted',physical:{whole:{truePeakDbfs:0.4}}}},'1':{audio:{status:'accepted',physical:{whole:{truePeakDbfs:0.6}}}}};
assert.ok(Shuffle.score([items[0],items[1]],{profiles:positivePeak})<0,'positive measured true peaks are not treated as unavailable');
// Sound-body proximity must matter independently of boundary descriptors.
const body=id=>({audio:{status:'accepted',physical:{whole:{rmsDbfs:id}}}});
const bodies={'0':body(-20),'1':body(-21),'2':body(-55)};
assert.ok(Shuffle.score([items[0],items[1]],{profiles:bodies})<Shuffle.score([items[0],items[2]],{profiles:bodies}));
assert.equal(Shuffle.score([items[0],items[1]],{profiles:{'0':body(NaN),'1':body(-21)}}),0);
const deepFreeze=x=>{Object.freeze(x);Object.values(x).forEach(v=>{if(v&&typeof v==='object')deepFreeze(v);});return x;};
deepFreeze(bodies);
for(const algorithm of algorithms) Shuffle.order(items,{...options,algorithm,profiles:bodies});
for(const bad of [NaN,Infinity,-1,1.5,20001]) assert.throws(()=>Shuffle.order(items,{budget:{constructions:1,localProposals:bad}}),/budget/i);
for(const archiveSize of [0,33,NaN,1.5]) assert.throws(()=>Shuffle.order(items,{archiveSize}),/archive/i);
for(const qualitySlack of [-1,NaN,Infinity,2]) assert.throws(()=>Shuffle.order(items,{qualitySlack}),/slack/i);
for(const windowSize of [-1,17,NaN,1.5]) assert.throws(()=>Shuffle.order(items,{windowSize}),/window/i);
// One movable swap gives an exact, decisive optimizer qualification.
const tiny=items.slice(0,3);
const tinyCost=(a,b)=>Number(a.entryId)<Number(b.entryId)?0:10;
for(const algorithm of ['ils','mmas']) for(let seed=0;seed<8;seed++) {
  const run=Shuffle.order(tiny,{...options,algorithm,seed,fixedPrefix:1,transitionCost:tinyCost,windowCost:()=>0});
  assert.equal(run.score,0,'bounded local search must solve the single movable swap');
}
const clustered=Object.fromEntries(items.map((x,i)=>[x.queueId,semantic(`cluster-${i%2}`)]));
for(const algorithm of ['ils','mmas']) {
  const varied=new Set(Array.from({length:12},(_,seed)=>ids(Shuffle.order(items,{...options,seed,algorithm,profiles:clustered,fixedPrefix:1}).items)));
  assert.ok(varied.size>=4,'informative profiles must not collapse every seed to one ordering');
}

// Independent directed/window reference, including inherited fixed history.
const fixture=items.slice(0,7);
const matrix=fixture.map((_,i)=>fixture.map((_,j)=>((i*17+j*11+i*j*3)%23)/7));
const edge=(a,b)=>matrix[Number(a.entryId)][Number(b.entryId)];
const window=(recent,current)=>recent.filter(x=>(Number(x.entryId)%3)===(Number(current.entryId)%3)).length*0.4;
const reference=(order,prefix=2)=>order.reduce((total,x,index)=> index<prefix?total:total+(index?edge(order[index-1],x):0)+window(order.slice(Math.max(0,index-3),index),x),0);
const cfg={...options,fixedPrefix:2,transitionCost:edge,windowCost:window,windowSize:3};
assert.ok(Math.abs(Shuffle.score(fixture,cfg)-reference(fixture))<1e-10);
assert.notEqual(edge(fixture[0],fixture[1]),edge(fixture[1],fixture[0]));
const optimum=oracle(fixture,2,reference);
const improvements={random:0,ils:0,mmas:0};
for(const algorithm of algorithms) for(let seed=0;seed<8;seed++) {
  const result=Shuffle.order(fixture,{...cfg,algorithm,seed});
  conserved(fixture,result.items,2);
  assert.ok(Math.abs(result.score-reference(result.items))<1e-9,'search score must match full independent directed/window evaluator');
  assert.ok(result.score>=optimum-1e-9,'heuristic cannot outperform the exhaustive optimum');
  if(result.score<result.baselineScore-1e-9) improvements[algorithm]++;
  assert.ok(result.score<=result.baselineScore+1e-9);
  assert.ok(result.stats.localProposals<=96);
  assert.ok(result.stats.constructions<=8);
}
assert.ok(improvements.ils>=4,'local search should improve a majority of this fixed directed fixture');
assert.ok(improvements.mmas>=4,'ant plus local search should improve a majority of this fixed fixture');
// The full prefix is held, so no suffix cost exists even with directed history.
assert.equal(Shuffle.score(fixture,{...cfg,fixedPrefix:fixture.length}),0);
assert.ok(Math.abs(Shuffle.score(fixture,{...cfg,fixedPrefix:0})-reference(fixture,0))<1e-10);
// Large supported queues must retain every occurrence with a bounded fallback.
const large=Array.from({length:4096},(_,i)=>item(`large-${i}`,String(i%337)));
const bounded=Shuffle.order(large,{...options,algorithm:'mmas',fixedPrefix:7});
conserved(large,bounded.items,7);
assert.equal(bounded.stats.fallback,'mmas-to-local-budget');
assert.ok(bounded.stats.localProposals<=16);
assert.ok(bounded.score<=bounded.baselineScore+1e-9);
assert.equal(bounded.stats.constructions,0);
const largeProfiles=Object.fromEntries(Array.from({length:337},(_,i)=>[String(i),semantic(`theme-${i%7}`)]));
for(const fixedPrefix of [7,4000]) {
  const run=Shuffle.order(large,{...options,profiles:largeProfiles,algorithm:'mmas',fixedPrefix});
  conserved(large,run.items,fixedPrefix);
  assert.equal(run.stats.localProposals,16);
  assert.equal(run.stats.extensionEvaluations,0);
  assert.equal(run.stats.fallback,'mmas-to-local-budget');
  assert.ok(run.score<=run.baselineScore+1e-9);
  const disabled=Shuffle.order(large,{...options,profiles:largeProfiles,algorithm:'mmas',fixedPrefix,budget:{constructions:0,localProposals:16}});
  assert.equal(disabled.stats.localProposals,0);
  assert.equal(disabled.score,disabled.baselineScore);
}
const randomFirst=Shuffle.order(items,{...options,algorithm:'random'}).items[0];
for(const algorithm of algorithms) assert.equal(Shuffle.order(items,{...options,algorithm}).items[0],randomFirst);
// Unaccepted proposals cannot influence playback.
assert.equal(Shuffle.score(items.slice(0,2),{profiles:{'0':semantic('longing'),'1':{semantic:{status:'proposed',themes:[{id:'longing',weight:1}]}}}}),0);
console.log('smart shuffle: occurrence, seed, neutrality, directed/window oracle and budget checks passed');
module.exports={oracle,permutations};
