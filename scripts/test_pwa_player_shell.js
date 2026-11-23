#!/usr/bin/env node
'use strict';
// Full application bootstrap and real DOM handlers. Geometry inputs below are
// controlled: these assertions cover scroll ownership, not WebKit compositing.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
async function boot({ios = true, touchApp = false, desktopApp = false} = {}) {
  const dom = new JSDOM(read('songs/paluke-bangaramayena/index.html'), {
    url: 'https://bhakti.eeshan.xyz/songs/paluke-bangaramayena/', runScripts:'outside-only', pretendToBeVisual:true,
  });
  const {window:w} = dom, d=w.document;
  w.navigator.standalone=ios;
  w.matchMedia = query => ({matches: query.includes('reduced-motion') || (query.includes('standalone') && (touchApp || (desktopApp && !query.includes('coarse'))))});
  w.console.warn = () => {}; // jsdom cannot execute the unrelated dynamic owner module.
  w.scrollTo = ({top}) => { w.scrollY=top; };
  w.HTMLElement.prototype.scrollTo = function({top}) { this.scrollTop=top; };
  w.HTMLElement.prototype.scrollIntoView = function() { this.nativeScrolls=(this.nativeScrolls||0)+1; };
  w.IntersectionObserver=class {observe(){} unobserve(){} disconnect(){}};
  w.ResizeObserver=class {observe(){} disconnect(){}};
  w.fetch=async url => ({ok:true,text:async()=>read(url==='/'?'index.html':url.replace(/^\//,'')+'index.html')});
  w.visualViewport=Object.assign(new w.EventTarget(),{height:844,offsetTop:0,scale:1});
  const audio=d.querySelector('audio'), player=d.getElementById('audioPlayer');
  const originalParent=player.parentElement, sources=[...audio.children];
  let loads=0;
  Object.defineProperties(audio,Object.fromEntries(Object.entries({paused:true,ended:false,readyState:1,currentTime:0,duration:368,error:null}).map(([k,v])=>[k,{value:v,writable:true,configurable:true}])));
  audio.load=()=>{loads++;}; audio.pause=()=>{audio.paused=true;};
  audio.play=()=>{audio.paused=false;audio.dispatchEvent(new w.Event('play'));return Promise.resolve();};
  for (const file of ['data/songs.js','songs/paluke-bangaramayena/data.js','assets/queue.js','assets/library.js','assets/song.js','assets/app.js']) w.eval(read(file));
  await new Promise(resolve=>setImmediate(resolve));
  return {dom,w,d,audio,player,originalParent,sources,loads:()=>loads,frame:()=>new Promise(resolve=>w.requestAnimationFrame(resolve))};
}
for (const mode of [{ios:true},{ios:false,touchApp:true},{ios:false},{ios:false,desktopApp:true}]) {
  test(`shell activation and persistent node identity ${JSON.stringify(mode)}`,async()=>{
    const app=await boot(mode);const {d,w}=app;
    try {
      const shell=d.querySelector('.app-shell'),scroll=d.querySelector('.app-scroll');
      if (!mode.ios&&!mode.touchApp) {assert.equal(shell,null);return;}
      assert.ok(shell&&scroll,'installed touch app has a dedicated scroller and shell');
      assert.equal(scroll.parentElement,shell);
      assert.equal(d.querySelector('.app-stage').parentElement,scroll);
      assert.equal(app.player.parentElement,shell);
      assert.equal(app.player.parentElement,app.originalParent,"never reparent persistent audio subtree");
      assert.deepEqual([...app.audio.children],app.sources);
      assert.equal(d.querySelector('audio'),app.audio);
      assert.equal(d.querySelector('#queueSheet').parentElement,shell);
      assert.equal(d.querySelector('.app-status').parentElement,shell);
      const css=d.createElement('style');css.textContent=read('assets/song.css')+read('assets/app.css');d.head.append(css);
      const style=w.getComputedStyle(app.player);
      assert.equal(style.position,'relative','player must not participate in fixed/sticky positioning');
      assert.equal(style.translate,'none');assert.equal(style.transform,'none');
      assert.equal(style.top,'auto');assert.equal(style.bottom,'auto');
      Object.assign(w.visualViewport,{height:300,offsetTop:120});
      w.visualViewport.dispatchEvent(new w.Event('resize'));await app.frame();
      assert.ok(!shell.classList.contains('has-keyboard-focus'),'stale visual bounds cannot shrink the unfocused shell');
      assert.equal(shell.style.height,'','rest height stays CSS-owned');
      const rules=[...css.sheet.cssRules];
      const rest=rules.find(rule=>rule.selectorText==='body.app-shell');
      assert.equal(rest.style.height,'100dvh','rest shell ignores stale VisualViewport dimensions');
      const row=rules.find(rule=>rule.selectorText==='.app-shell .audio-player');
      assert.equal(row.style['grid-row'],'2');
      assert.equal(rules.find(rule=>rule.selectorText==='.app-scroll').style.overflow,'auto');
      assert.equal(rules.find(rule=>rule.selectorText==='.app-scroll').style.getPropertyValue('isolation'),'isolate','nested tag rows stay inside the content scroller');
      assert.equal(rest.style['grid-template-rows'],'minmax(0, 1fr) auto');
      scroll.scrollTop=500;
      const input=d.createElement('input');scroll.append(input);input.focus();
      assert.ok(shell.classList.contains('has-keyboard-focus'));
      input.blur();
      assert.ok(!shell.classList.contains('has-keyboard-focus'),'blur immediately restores CSS height even if native values stay stale');
      assert.equal(scroll.scrollTop,500);
      input.readOnly=true;input.focus();assert.ok(!shell.classList.contains('has-keyboard-focus'));input.blur();
      for (const type of ['range','checkbox','button']) {input.readOnly=false;input.type=type;input.focus();assert.ok(!shell.classList.contains('has-keyboard-focus'),type);input.blur();}
      const editable=d.createElement('div');editable.contentEditable='true';editable.setAttribute('contenteditable','true');editable.tabIndex=0;scroll.append(editable);editable.focus();assert.ok(shell.classList.contains('has-keyboard-focus'));editable.blur();
      w.dispatchEvent(new w.Event('orientationchange'));await app.frame();
      assert.equal(d.querySelector('.app-scroll'),scroll,'rotation never replaces scroll owner');
    } finally {app.dom.window.close();}
  });
}
test('full song -> library -> same song keeps content/audio and restores inner scroll',async()=>{
  const app=await boot();const {w,d,audio}=app;
  try {
    const scroller=d.querySelector('.app-scroll');assert.ok(scroller);
    scroller.scrollTop=1200;audio.currentTime=88;const loads=app.loads();
    const line=d.querySelector('article.line');
    await w.BHAKTI_APP.showLibrary();assert.equal(scroller.scrollTop,0);assert.equal(w.scrollY,0);
    await w.BHAKTI_APP.showSong('paluke-bangaramayena');
    assert.equal(scroller.scrollTop,1200);assert.equal(d.querySelector('article.line'),line);
    assert.equal(audio.currentTime,88);assert.equal(app.loads(),loads);assert.equal(d.querySelector('audio'),audio);
    scroller.scrollTop=1325;await w.BHAKTI_APP.showSong('paluke-bangaramayena');assert.equal(scroller.scrollTop,1325);
  } finally {app.dom.window.close();}
});
test('lyric following centers only the internal scroll owner, including boundaries',async()=>{
  const app=await boot();const {w,d}=app;
  try {
    const scroller=d.querySelector('.app-scroll');assert.ok(scroller);
    Object.defineProperties(scroller,{clientHeight:{value:700},scrollHeight:{value:5000}});
    scroller.getBoundingClientRect=()=>({top:20,height:700});
    const line=d.querySelector('article.line');
    line.getBoundingClientRect=()=>({top:520,height:100});
    scroller.scrollTop=1000;
    w.eval('scrollReaderArticle(document.querySelector("article.line"))');
    assert.equal(scroller.scrollTop,1200);assert.equal(w.scrollY,0);assert.equal(line.nativeScrolls,undefined);
    line.getBoundingClientRect=()=>({top:-2000,height:100});
    w.eval('scrollReaderArticle(document.querySelector("article.line"))');assert.equal(scroller.scrollTop,0);
    line.getBoundingClientRect=()=>({top:10000,height:100});
    w.eval('scrollReaderArticle(document.querySelector("article.line"))');assert.equal(scroller.scrollTop,4300);
  } finally {app.dom.window.close();}
});

test('real timeupdate and follow control scroll only the content region',async()=>{
  const app=await boot();const {w,d,audio}=app;
  try {
    const scroller=d.querySelector('.app-scroll');
    Object.defineProperties(scroller,{clientHeight:{value:700},scrollHeight:{value:5000}});
    scroller.getBoundingClientRect=()=>({top:20,height:700});
    const line=d.querySelector('article.line');line.getBoundingClientRect=()=>({top:520,height:100});
    scroller.scrollTop=1000;audio.currentTime=Number(line.dataset.start)+0.01;
    audio.dispatchEvent(new w.Event('timeupdate'));
    assert.equal(scroller.scrollTop,1200);assert.ok(line.classList.contains('is-singing'));
    d.getElementById('songSync').click();scroller.scrollTop=500;
    d.getElementById('songSync').click();assert.equal(scroller.scrollTop,700);
    assert.equal(w.scrollY,0);assert.equal(line.nativeScrolls,undefined);
  } finally {app.dom.window.close();}
});
test('inner scrolling dismisses meanings but scrolling inside a meaning preserves it',async()=>{
  const app=await boot();const {w,d}=app;
  try {
    const word=d.querySelector('.word-link');word.click();
    const tip=d.querySelector('.word-tooltip');assert.equal(tip.hidden,false);
    tip.dispatchEvent(new w.Event('scroll'));assert.equal(tip.hidden,false);
    d.querySelector('.app-scroll').dispatchEvent(new w.Event('scroll'));
    assert.equal(tip.hidden,true);assert.equal(d.querySelectorAll('.word-link.is-hi').length,0);
    word.click();assert.equal(tip.hidden,false,'one tap reopens after scroll dismissal');
  } finally {app.dom.window.close();}
});
test('navigation clears focused search before detaching it, without losing reader scroll',async()=>{
  const app=await boot();const {w,d}=app;
  try {
    const scroller=d.querySelector('.app-scroll');scroller.scrollTop=600;
    await w.BHAKTI_APP.showLibrary();const input=d.querySelector('input[type="search"]');input.focus();
    assert.ok(d.body.classList.contains('has-keyboard-focus'));
    Object.assign(w.visualViewport,{height:300,offsetTop:120});
    await w.BHAKTI_APP.showSong('paluke-bangaramayena');
    assert.ok(!d.body.classList.contains('has-keyboard-focus'));assert.equal(scroller.scrollTop,600);assert.equal(w.scrollY,0);
  } finally {app.dom.window.close();}
});

test('playlist open/close preserves inner scroll and library popups dismiss on it',async()=>{
  const app=await boot();const {w,d,audio}=app;
  try {
    await w.BHAKTI_APP.showLibrary();const scroller=d.querySelector('.app-scroll');
    const preface=d.querySelector('.preface-token');preface.click();
    const tip=d.getElementById('prefaceTooltip');assert.equal(tip.hidden,false);
    scroller.dispatchEvent(new w.Event('scroll'));assert.equal(tip.hidden,true);
    d.querySelector('[data-queue-choices]').click();
    const menu=d.getElementById('library-queue-choices');assert.equal(menu.hidden,false);
    menu.querySelector('[data-queue-position="end"]').click();
    await w.BHAKTI_APP.showSong('paluke-bangaramayena');
    const queue=d.getElementById('queueSheet'),toggle=d.querySelector('[aria-controls="queueSheet"]');
    scroller.scrollTop=1200;audio.currentTime=88;toggle.click();
    assert.equal(queue.hidden,false);assert.ok(d.body.classList.contains('queue-open'));
    const list=queue.querySelector('.queue-list');list.scrollTop=300;list.dispatchEvent(new w.Event('scroll'));
    assert.equal(scroller.scrollTop,1200);assert.equal(audio.currentTime,88);
    toggle.click();assert.equal(queue.hidden,true);assert.ok(!d.body.classList.contains('queue-open'));
    assert.equal(scroller.scrollTop,1200);
    const css=read('assets/app.css');
    const sheet=d.createElement('style');sheet.textContent=css;d.head.append(sheet);
    const rules=[...sheet.sheet.cssRules];
    assert.equal(rules.find(r=>r.selectorText==='.app-shell .queue-sheet').style.position,'absolute');
    const mobile=rules.find(r=>r.conditionText==='(max-width: 1100px)');
    assert.equal([...mobile.cssRules].find(r=>r.selectorText==='.app-shell.queue-open .app-scroll').style.overflow,'hidden');
  } finally {app.dom.window.close();}
});
