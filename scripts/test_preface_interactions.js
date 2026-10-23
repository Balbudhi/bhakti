#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../assets/library.js'), 'utf8');
const code = source.slice(source.indexOf('const wirePreface ='), source.indexOf('const mount ='));

function setup({hover = false} = {}) {
  const events = () => ({listeners: {}, addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    emit(type, event = {}) { for (const fn of this.listeners[type] || []) fn({preventDefault() {}, stopPropagation() {}, ...event}); }});
  const document = events();
  const window = {...events(), innerWidth:390, matchMedia:()=>({matches:hover})};
  const token = index => {
    const classes = new Set();
    return {dataset:{wordI:index,gloss:'Meaning'}, keyboard:false,
      classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),contains:c=>classes.has(c)},
      closest(selector) {return selector === '.preface-token' ? this : null;},
      matches(selector) {return selector === ':focus-visible' && this.keyboard;},
      contains(other) {return this === other;},
      getBoundingClientRect:()=>({top:100,bottom:124,left:20,width:60}),
      click() {preface.emit('click',{target:this});},
    };
  };
  const first=token('0'), linked=token('0'), second=token('1');
  const tokens=[first,linked,second];
  const preface={...events(), contains:node=>tokens.includes(node), querySelectorAll:selector=>selector.endsWith('.is-hi') ? tokens.filter(t=>t.classList.contains('is-hi')) : tokens};
  const tooltip={hidden:true,style:{},getBoundingClientRect:()=>({width:100,height:40})};
  const root={querySelector:selector=>selector === '.library-intro' ? preface : tooltip};
  vm.runInNewContext(code+'\nwirePreface(root);',{window,document,root});
  return {window,document,preface,tooltip,first,linked,second};
}
const selected = app => app.preface.emit('click',{target:app.first});
const clear = app => {assert.equal(app.tooltip.hidden,true); assert.equal(app.first.classList.contains('is-hi'),false); assert.equal(app.linked.classList.contains('is-hi'),false);};

test('touch contact previews nothing; an explicit tap selects and a second tap clears',()=>{
  const app=setup();
  app.preface.emit('pointerover',{target:app.first,pointerType:'touch'});
  app.preface.emit('focusin',{target:app.first});
  clear(app);
  selected(app); assert.equal(app.tooltip.hidden,false); assert.equal(app.linked.classList.contains('is-hi'),true);
  selected(app); clear(app);
});
test('scroll dismisses linked highlighting and selection so the next tap opens immediately',()=>{
  const app=setup(); selected(app); app.window.emit('scroll'); clear(app);
  selected(app); assert.equal(app.tooltip.hidden,false);
});
test('Escape and navigation cleanup dismiss both preview and selected meanings',()=>{
  for (const sticky of [false,true]) for (const event of ['Escape','bhakti:clear-preface']) {
    const app=setup({hover:true});
    if(sticky) selected(app); else {app.first.keyboard=true;app.preface.emit('focusin',{target:app.first});}
    assert.equal(app.tooltip.hidden,false);
    if(event==='Escape') app.document.emit('keydown',{key:'Escape',target:app.first});
    else app.document.emit(event);
    clear(app); selected(app); assert.equal(app.tooltip.hidden,false);
  }
});
test('mouse preview and keyboard focus work; touch contact on a hybrid device does not preview',()=>{
  const app=setup({hover:true});
  app.preface.emit('pointerover',{target:app.first,pointerType:'touch'}); clear(app);
  app.preface.emit('pointerover',{target:app.first,pointerType:'mouse'}); assert.equal(app.tooltip.hidden,false);
  app.preface.emit('pointerout',{target:app.first,relatedTarget:null,pointerType:'mouse'}); clear(app);
  app.first.keyboard=true;app.preface.emit('focusin',{target:app.first}); assert.equal(app.tooltip.hidden,false);
  app.preface.emit('focusout',{target:app.first,relatedTarget:null}); clear(app);
});
test('outside click dismisses and hovering another token never replaces a pinned meaning',()=>{
  const app=setup({hover:true}); selected(app);
  app.preface.emit('pointerover',{target:app.second,pointerType:'mouse'});
  assert.equal(app.first.classList.contains('is-hi'),true);
  assert.equal(app.second.classList.contains('is-hi'),false);
  app.document.emit('click',{target:{closest:()=>null}}); clear(app);
});

test('resize and browser navigation clear selection before reopening',()=>{
  for(const event of ['resize','popstate']) {
    const app=setup();selected(app);app.window.emit(event);clear(app);
    selected(app);assert.equal(app.tooltip.hidden,false);
  }
});
