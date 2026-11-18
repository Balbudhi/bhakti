#!/usr/bin/env node
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const sourceRoot=path.resolve(__dirname,'..');
const root=path.join(sourceRoot,'_site');
assert.ok(fs.existsSync(path.join(root,'index.html')), 'Assemble the public artifact before testing deployment assets');
const catalogueContext={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'data/songs.js'),'utf8'),catalogueContext);
const songs=catalogueContext.window.BHAKTI_SONGS;
const pages=['index.html',...songs.map(s=>`songs/${s.slug}/index.html`)];
const required=['/assets/release-map.js','/assets/shuffle-client.js','/assets/queue.js','/assets/app.js'];
for(const page of pages) {
  const html=fs.readFileSync(path.join(root,page),'utf8');
  const sources=[...html.matchAll(/<script\b[^>]*src="([^"]+)"/g)].map(m=>m[1].split('?')[0]);
  for(const asset of required) assert.equal(sources.filter(src=>src===asset).length,1,`${page} must load ${asset} once`);
  assert.ok(sources.indexOf(required[0])<sources.indexOf(required[2]));
  assert.ok(sources.indexOf(required[1])<sources.indexOf(required[3]));
  assert.ok(!sources.includes('/data/shuffle-profiles.js') && !sources.includes('/assets/shuffle.js'), `${page}: shuffle must be lazy`);
  assert.ok(sources.indexOf(required[2])<sources.indexOf(required[3]));
}
const sw=fs.readFileSync(path.join(root,'sw.js'),'utf8');
const release=vm.runInNewContext(sw+'\nRELEASE;',{self:{addEventListener(){}}});
for(const asset of required) assert.ok(release.shell.includes(release.paths[asset]),`Offline shell lacks ${asset}`);
for(const asset of ['/data/shuffle-profiles.js','/assets/shuffle.js','/assets/shuffle-worker.js']) {
  assert.ok(release.paths[asset], `Missing lazy resource ${asset}`);
  assert.ok(!release.shell.includes(release.paths[asset]), `Shuffle must not block installation: ${asset}`);
}
// Assembly applies the same lazy runtime adoption to existing and future
// generated pages; reviewed source HTML keeps its content identity.
const assembler=fs.readFileSync(path.join(sourceRoot,'scripts/assemble_public_site.py'),'utf8');
assert.ok(assembler.includes('/assets/shuffle-client.js'));
const publicContext={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'data/shuffle-profiles.js'),'utf8'),publicContext);
const bundle=publicContext.window.BHAKTI_SHUFFLE_PROFILES;
assert.equal(bundle.schemaVersion,1);
assert.equal(bundle.taxonomyVersion,1);
assert.ok(typeof bundle.revision==='string' && bundle.revision.length>0);
assert.equal(bundle.revision,catalogueContext.window.BHAKTI_SHUFFLE_REVISION,'Deployed catalogue and profile snapshot must match');
assert.deepEqual(Object.keys(bundle.profiles).sort(),Array.from(songs,s=>s.queueId).sort(),'Every catalogue song has an explicit profile status');
console.log(`shuffle asset adoption: ${pages.length} entrypoints, offline shell and exact profile population passed`);
