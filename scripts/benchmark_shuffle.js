#!/usr/bin/env node
'use strict';
// Bounded numerical benchmark, not a listening study. No network or model calls.
// node scripts/benchmark_shuffle.js [--quick] [--actual --profiles data/shuffle-profiles.js]
const {performance} = require('node:perf_hooks');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const Shuffle = require('../assets/shuffle.js');
const root = path.resolve(__dirname, '..');
const quick = process.argv.includes('--quick');
const actual = process.argv.includes('--actual');
const profileFlag = process.argv.indexOf('--profiles');
const loadGlobal = (filename, name) => {
  const source = fs.readFileSync(filename, 'utf8');
  const sandbox = {window:{}};
  vm.runInNewContext(source, sandbox, {timeout:1000});
  return {value:sandbox.window[name], hash:crypto.createHash('sha256').update(source).digest('hex')};
};
const synthetic = size => {
  const items = Array.from({length:size}, (_,i) => ({entryId:String(i), queueId:String(i), slug:String(i)}));
  const profiles = Object.fromEntries(items.map((x,i) => [x.queueId, i%11===0 ? {} : {
    semantic:{status:'accepted',themes:[{id:`theme-${i%7}`,weight:1}],actions:[],subjects:[]},
    audio:{status:'accepted',physical:{whole:{rmsDbfs:-35+i%20,centroidHz:150+100*(i%13)},profiles:{beginning:{rmsDbfs:-30+i%15},end:{rmsDbfs:-35+(i*3)%20}}}},
  }]));
  return {name:`synthetic-${size}`,items,profiles};
};
let cases;
if (actual) {
  if (profileFlag<0 || !process.argv[profileFlag+1]) throw new Error('--actual requires --profiles path');
  const catalogue = loadGlobal(path.join(root,'data/songs.js'),'BHAKTI_SONGS');
  const projection = loadGlobal(path.resolve(process.argv[profileFlag+1]),'BHAKTI_SHUFFLE_PROFILES');
  if (projection.value?.schemaVersion!==1 || !projection.value.profiles) throw new Error('profile schema mismatch');
  cases = [{name:'actual-catalogue',items:Array.from(catalogue.value,(x,i)=>({...x,entryId:String(i)})),profiles:projection.value.profiles,catalogueHash:catalogue.hash,profilesHash:projection.hash}];
} else cases = (quick?[32]:[32,337]).map(synthetic);
const seeds = Array.from({length:quick?2:16},(_,i)=>i+1);
const mean = xs => xs.reduce((a,b)=>a+b,0)/xs.length;
const summary = xs => {
  const sorted = [...xs].sort((a,b)=>a-b);
  const average = mean(xs);
  const se = xs.length>1 ? Math.sqrt(xs.reduce((sum,x)=>sum+(x-average)**2,0)/(xs.length-1)/xs.length) : 0;
  return {mean:average,median:sorted[Math.floor(sorted.length/2)],min:sorted[0],max:sorted.at(-1),approximate95NormalInterval:[average-1.96*se,average+1.96*se]};
};
const cohortDefinition = testCase => {
  const themeSupport=new Map();
  const themeIds=item=>new Set((testCase.profiles[item.queueId]?.semantic?.status==='accepted' ? testCase.profiles[item.queueId].semantic.themes||[] : []).filter(x=>x.weight>0).map(x=>x.id));
  testCase.items.forEach(item=>themeIds(item).forEach(id=>themeSupport.set(id,(themeSupport.get(id)||0)+1)));
  const rareLimit=Math.max(2,Math.ceil(testCase.items.length*0.02));
  const memberships=new Map(testCase.items.map(item=>{
    const p=testCase.profiles[item.queueId]||{};
    const semantic=p.semantic?.status==='accepted' && ['themes','actions','subjects'].some(key=>p.semantic[key]?.some(x=>x.weight>0));
    const physical=p.audio?.physical;
    const acoustic=p.audio?.status==='accepted' && [physical?.whole,...Object.values(physical?.profiles||{})].some(part=>part&&['integratedLufs','truePeakDbfs','rmsDbfs','centroidHz'].some(field=>Number.isFinite(part[field])&&(field!=='centroidHz'||part[field]>0)));
    return [item.queueId,{metadataNone:!semantic&&!acoustic,semanticUnavailable:!semantic,themesUnavailable:!themeIds(item).size,audioUnavailable:!acoustic,rareTheme:[...themeIds(item)].some(id=>themeSupport.get(id)<=rareLimit)}];
  }));
  const names=['metadataNone','semanticUnavailable','themesUnavailable','audioUnavailable','rareTheme'];
  const totals=Object.fromEntries(names.map(name=>[name,testCase.items.slice(1).filter(item=>memberships.get(item.queueId)[name]).length]));
  return {themeIds,memberships,names,totals,rareLimit};
};
const orderMetrics = (ordered, cohorts) => {
  let longest=0, streaks=new Map();
  for(const item of ordered) {
    const next=new Map();
    for(const id of cohorts.themeIds(item)) {const count=(streaks.get(id)||0)+1; next.set(id,count); longest=Math.max(longest,count);}
    streaks=next;
  }
  const early=ordered.slice(1,21), tail=ordered.length>1?ordered.slice(-Math.min(20,ordered.length-1)):[];
  const counts=rows=>Object.fromEntries(cohorts.names.map(name=>[name,rows.filter(item=>cohorts.memberships.get(item.queueId)[name]).length]));
  return {longestThemeRun:longest,first20Movable:early.map(x=>x.queueId),tail20:tail.map(x=>x.queueId),earlyCohorts:counts(early),early10Cohorts:counts(ordered.slice(1,11)),early50Cohorts:counts(ordered.slice(1,51)),tailCohorts:counts(tail)};
};
const diversity = new Map();
const collectDiversity = (key, ordered) => {
  if(!diversity.has(key)) diversity.set(key,{edges:new Set(),edgeCount:0,first20PositionCounts:{}});
  const acc=diversity.get(key);
  for(let i=1;i<ordered.length;i++) {acc.edges.add(JSON.stringify([ordered[i-1].queueId,ordered[i].queueId]));acc.edgeCount++;}
  ordered.slice(1,21).forEach((item,index)=>{
    const row=acc.first20PositionCounts[item.queueId] ||= Array(20).fill(0); row[index]++;
  });
};
const results = [], calibrations = [], cohortProbes = [];

const totalStart = performance.now();
for (const testCase of cases) {
  const cohorts=cohortDefinition(testCase);
  testCase.cohortDefinition={rareThemeMaximumOccurrenceSupport:cohorts.rareLimit,movableCohortTotals:cohorts.totals,anchorExcludedFromEarlyWindow:true};
  const common = {profiles:testCase.profiles,fixedPrefix:1,qualitySlack:0.02};
  const timed = (algorithm,constructions,localProposals,seed) => {
    const start=performance.now();
    Shuffle.order(testCase.items,{...common,seed,algorithm,budget:{constructions,localProposals}});
    return performance.now()-start;
  };
  // Disjoint calibration seeds. Match measured MMAS8 time through deterministic ILS work.
  timed('ils',8,1024,100001); timed('mmas',8,256,100001);
  const target = mean([100002,100003,100004].map(seed=>timed('mmas',8,256,seed)));
  let proposals = 1024;
  for (let trial=0;trial<2;trial++) {
    const elapsed=mean([100005,100006].map(seed=>timed('ils',8,proposals,seed)));
    proposals=Math.max(64,Math.min(20000,Math.round(proposals*target/Math.max(0.01,elapsed))));
  }
  calibrations.push({case:testCase.name,targetMmas8Milliseconds:target,ilsLocalProposals:proposals});
  const variants = [
    {name:'random',algorithm:'random',constructions:0,localProposals:0},
    {name:'ils-construction',algorithm:'ils',constructions:8,localProposals:0},
    {name:'ils-local256',algorithm:'ils',constructions:8,localProposals:256},
    {name:'ils-local1024',algorithm:'ils',constructions:8,localProposals:1024},
    {name:'ils-local4096',algorithm:'ils',constructions:8,localProposals:4096},
    {name:'ils-time-matched',algorithm:'ils',constructions:8,localProposals:proposals},
    {name:'mmas8-construction',algorithm:'mmas',constructions:8,localProposals:0},
    {name:'mmas8-local256',algorithm:'mmas',constructions:8,localProposals:256},
    {name:'no-pheromone8-local256',algorithm:'mmas',constructions:8,localProposals:256,disablePheromone:true},
    {name:'mmas16-local256',algorithm:'mmas',constructions:16,localProposals:256},
    {name:'no-pheromone16-local256',algorithm:'mmas',constructions:16,localProposals:256,disablePheromone:true},
  ];
  for (const seed of seeds) for (let offset=0;offset<variants.length;offset++) {
    if (performance.now()-totalStart>120000) throw new Error('benchmark exceeded 120-second wall cap');
    const variant=variants[(offset+seed)%variants.length];
    const start=performance.now();
    const cpuStart=process.cpuUsage();
    const run=Shuffle.order(testCase.items,{...common,...variant,seed,budget:{constructions:variant.constructions,localProposals:variant.localProposals}});
    const cpu=process.cpuUsage(cpuStart);
    const elapsed=performance.now()-start;
    collectDiversity(`${testCase.name}:${variant.name}`,run.items);
    results.push({case:testCase.name,size:testCase.items.length,variant:variant.name,seed,milliseconds:elapsed,cpuMilliseconds:(cpu.user+cpu.system)/1000,score:run.score,baseline:run.baselineScore,requestedLocalProposals:variant.localProposals,...run.stats,...orderMetrics(run.items,cohorts),...(seed===1?{orderQueueIds:run.items.map(x=>x.queueId)}:{})});
  }
  if(actual&&!quick) {
    const runs=results.filter(x=>x.case===testCase.name);
    const targetElapsed=mean(runs.filter(x=>x.variant==='mmas8-local256').map(x=>x.milliseconds));
    const eligible=variants.filter(v=>v.algorithm!=='random'&&mean(runs.filter(x=>x.variant===v.name).map(x=>x.milliseconds))<=targetElapsed*1.25);
    eligible.sort((a,b)=>mean(runs.filter(x=>x.variant===a.name).map(x=>x.score))-mean(runs.filter(x=>x.variant===b.name).map(x=>x.score)));
    const selected=eligible[0]||variants.find(v=>v.name==='ils-local256');
    const probe={case:testCase.name,selectedVariant:selected.name,selection:'Lowest numerical objective among measured variants within1.25x MMAS8 mean elapsed; no listener claim.',runs:[]};
    const production=variants.find(v=>v.name==='ils-local256');
    const probeVariants=[selected,...(selected.name===production.name?[]:[production]),variants[0]];
    for(let i=0;i<128;i++) for(const variant of probeVariants) {
      if(performance.now()-totalStart>120000) throw new Error('benchmark exceeded120-second wall cap');
      const seed=200000+i;
      const run=Shuffle.order(testCase.items,{...common,...variant,seed,budget:{constructions:variant.constructions,localProposals:variant.localProposals}});
      collectDiversity(`${testCase.name}:probe:${variant.name}`,run.items);
      probe.runs.push({variant:variant.name,seed,score:run.score,...orderMetrics(run.items,cohorts)});
    }
    cohortProbes.push(probe);
  }
}
const summaries = [], comparisons = [];
for (const testCase of cases) {
  const records=results.filter(x=>x.case===testCase.name);
  for (const variant of [...new Set(records.map(x=>x.variant))]) {
    const group=records.filter(x=>x.variant===variant);
    summaries.push({case:testCase.name,variant,milliseconds:summary(group.map(x=>x.milliseconds)),cpuMilliseconds:summary(group.map(x=>x.cpuMilliseconds)),gainOverSeededRandom:summary(group.map(x=>x.baseline-x.score)),longestThemeRun:summary(group.map(x=>x.longestThemeRun)),earlyCohorts:Object.fromEntries(Object.keys(group[0].earlyCohorts).map(name=>[name,summary(group.map(x=>x.earlyCohorts[name]))])),tailCohorts:Object.fromEntries(Object.keys(group[0].tailCohorts).map(name=>[name,summary(group.map(x=>x.tailCohorts[name]))]))});
  }
  for (const [left,right] of [['mmas8-local256','ils-time-matched'],['mmas8-local256','no-pheromone8-local256'],['mmas16-local256','no-pheromone16-local256']]) {
    const pairs=seeds.map(seed=>[records.find(x=>x.variant===left&&x.seed===seed),records.find(x=>x.variant===right&&x.seed===seed)]);
    comparisons.push({case:testCase.name,left,right,positiveMeansLeftLowerCost:summary(pairs.map(([a,b])=>b.score-a.score)),leftOverRightMeanElapsed:mean(pairs.map(([a])=>a.milliseconds))/mean(pairs.map(([,b])=>b.milliseconds)),leftOverRightMeanCpu:mean(pairs.map(([a])=>a.cpuMilliseconds))/mean(pairs.map(([,b])=>b.cpuMilliseconds))});
  }
}
const cohortProbeSummaries=cohortProbes.flatMap(probe=>{
  const controls=probe.runs.filter(x=>x.variant==='random');
  return [...new Set(probe.runs.filter(x=>x.variant!=='random').map(x=>x.variant))].map(variant=>{
    const selected=probe.runs.filter(x=>x.variant===variant);
    const paired=(field,name)=>summary(selected.map((x,i)=>name?x[field][name]-controls[i][field][name]:x[field]-controls[i][field]));
    return {case:probe.case,selectedVariant:variant,productionDefault:variant==='ils-local256',runsPerVariant:selected.length,positiveMeansSelectedMore: {
      longestThemeRun:paired('longestThemeRun'),
      earlyCohorts:Object.fromEntries(Object.keys(selected[0].earlyCohorts).map(name=>[name,paired('earlyCohorts',name)])),
      early10Cohorts:Object.fromEntries(Object.keys(selected[0].early10Cohorts).map(name=>[name,paired('early10Cohorts',name)])),
      early50Cohorts:Object.fromEntries(Object.keys(selected[0].early50Cohorts).map(name=>[name,paired('early50Cohorts',name)])),
      tailCohorts:Object.fromEntries(Object.keys(selected[0].tailCohorts).map(name=>[name,paired('tailCohorts',name)])),
    }};
  });
});
const sourceRevision=execFileSync('git',['rev-parse','HEAD'],{cwd:root,env:{...process.env,DEVELOPER_DIR:'/Library/Developer/CommandLineTools'},encoding:'utf8'}).trim();
console.log(JSON.stringify({notice:'Numerical objective only; provisional weights. Calibration is approximate elapsed matching, not identical work. Normal intervals are descriptive across paired seeds on the same instance, not population/listener inference.',sourceRevision,engineSha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'assets/shuffle.js'))).digest('hex'),benchmarkSha256:crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),node:process.version,cases:cases.map(({items,profiles,...rest})=>rest),seeds,calibrations,summaries,comparisons,diversity:[...diversity].map(([key,value])=>({key,uniqueAdjacencies:value.edges.size,totalAdjacencies:value.edgeCount,uniqueFraction:value.edges.size/value.edgeCount,first20PositionCounts:value.first20PositionCounts})),cohortProbes,cohortProbeSummaries,results},null,2));
