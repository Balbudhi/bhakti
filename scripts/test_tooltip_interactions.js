#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../assets/song.js'), 'utf8');
const tooltipCode = source.slice(source.indexOf('let tooltipEl = null;'), source.indexOf('/* =============================================================\n   KARAOKE'));
const indicesCode = source.slice(source.indexOf('function indicesFrom('), source.indexOf('function glossFor('));

function setup({ hover = false, overflow = true } = {}) {
  const target = () => ({ listeners: {}, addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    emit(type, event = {}) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {}, stopPropagation() {}, ...event }); } });
  const document = Object.assign(target(), { activeElement: null, body: { appendChild() {} },
    querySelector: () => null,
    documentElement: { clientWidth: 844 }, getElementById: () => ({ getBoundingClientRect: () => ({ top: 0 }) }) });
  function element(kind, index = '') {
    const classes = new Set();
    const node = Object.assign(target(), { kind, hidden: false, style: {}, dataset: { wordI: index, gloss: 'A long contextual meaning' },
      tabIndex: -1, scrollTop: 0, scrollHeight: overflow ? 177 : 60, clientHeight: 80,
      classList: { contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name),
        toggle(name, yes) { if (yes) classes.add(name); else classes.delete(name); } },
      setAttribute(name, value) { this[name] = String(value); },
      removeAttribute(name) { delete this[name]; },
      contains(other) { return this === other; },
      closest(selector) { return selector === '.word-link' && kind === 'word' ? this : selector === '.line' && kind === 'word' ? article : null; },
      getBoundingClientRect() { return { left: 200, right: 400, top: 180, bottom: 205, width: 200, height: parseFloat(this.style.maxHeight) || 80 }; },
      getClientRects() { return [this.getBoundingClientRect()]; },
      focus() { document.activeElement = this; },
      click() { root.emit('click', { target: this }); },
    });
    return node;
  }
  const word = element('word', '0'); const linked = element('word', '0'); const other = element('word', '1');
  const words = [word, linked, other];
  const article = { querySelectorAll: selector => selector === '.word-link' ? words : words.filter(w => w.classList.contains('is-hi')) };
  const root = Object.assign(target(), { contains: node => words.includes(node), querySelectorAll: () => words.filter(w => w.classList.contains('is-hi')) });
  let tip;
  document.createElement = () => (tip = element('tip'));
  const window = Object.assign(target(), { innerHeight: 390, scrollX: 0, scrollY: 0, matchMedia: () => ({ matches: hover }) });
  const context = vm.createContext({ window, document, Set, WeakSet, console });
  vm.runInContext(indicesCode + '\n' + tooltipCode, context);
  context.wireInteractions(root);
  return { root, window, document, word, linked, other, tip: () => tip, wireRoot: context.wireInteractions };
}

function select(app, keyboard = false) {
  if (keyboard) {
    app.word.focus();
    app.document.emit('keydown', { target: app.word, key: 'Tab' });
    app.document.emit('keydown', { target: app.word, key: 'Enter' });
  } else app.root.emit('click', { target: app.word });
}

test('selected overflow is interactive and keyboard reachable; Escape restores its anchor', () => {
  const app = setup(); select(app, true); const tip = app.tip();
  assert.equal(tip.classList.contains('is-interactive'), true);
  assert.equal(tip.tabIndex, 0);
  assert.equal(app.document.activeElement, tip);
  assert.equal(app.word.classList.contains('is-hi'), true);
  assert.equal(app.linked.classList.contains('is-hi'), true);
  assert.equal(app.other.classList.contains('is-hi'), false);
  app.document.emit('keydown', { target: tip, key: 'Escape' });
  assert.equal(tip.hidden, true);
  assert.equal(tip.tabIndex, -1);
  assert.equal(app.document.activeElement, app.word);
  assert.equal(app.linked.classList.contains('is-hi'), false);
});

test('inside click and tooltip scroll preserve selection; outside click closes it', () => {
  const app = setup(); select(app); const tip = app.tip();
  tip.scrollTop = 34;
  app.document.emit('click', { target: tip });
  assert.equal(tip.hidden, false);
  app.window.emit('scroll', { target: tip });
  assert.equal(tip.hidden, false);
  assert.equal(tip.scrollTop, 34);
  assert.equal(app.linked.classList.contains('is-hi'), true);
  app.document.emit('click', { target: { closest: () => null } });
  assert.equal(tip.hidden, true);
  assert.equal(app.linked.classList.contains('is-hi'), false);
});

test('focus leaving selected tooltip closes without stealing focus; document scroll closes', () => {
  const app = setup(); select(app, true); const tip = app.tip();
  app.other.focus(); tip.emit('focusout', { target: tip, relatedTarget: app.other });
  assert.equal(tip.hidden, true);
  assert.equal(app.document.activeElement, app.other);
  select(app); app.window.emit('scroll', { target: app.document });
  assert.equal(tip.hidden, true);
});

test('hover-only tooltip remains noninteractive and closes on mouseout', () => {
  const app = setup({ hover: true });
  app.root.emit('pointerover', { target: app.word }); const tip = app.tip();
  assert.equal(tip.classList.contains('is-interactive'), false);
  assert.equal(tip.tabIndex, -1);
  app.root.emit('pointerout', { target: app.word, relatedTarget: null });
  assert.equal(tip.hidden, true);
});

test('short selected tooltip does not add a tab stop or move keyboard focus', () => {
  const app = setup({ overflow: false }); select(app, true);
  assert.equal(app.tip().tabIndex, -1);
  assert.equal(app.document.activeElement, app.word);
});

test('selecting another word resets prior tooltip scroll position', () => {
  const app = setup(); select(app); app.tip().scrollTop = 34;
  app.root.emit('click', { target: app.other });
  assert.equal(app.tip().scrollTop, 0);
  assert.equal(app.other.classList.contains('is-hi'), true);
  assert.equal(app.word.classList.contains('is-hi'), false);
});

test('document keyboard handlers do not activate a word owned by another reader root', () => {
  const app = setup(); let clicks = 0;
  const foreignWord = { closest() { return this; }, click() { clicks++; } };
  app.document.emit('keydown', { target: foreignWord, key: 'Enter' });
  assert.equal(clicks, 0);
});

test('clicking the anchor again closes a selected tooltip even after focusing its text', () => {
  const app = setup(); select(app); const tip = app.tip(); tip.focus();
  app.root.emit('pointerdown', { target: app.word });
  tip.emit('focusout', { target: tip, relatedTarget: app.word });
  app.root.emit('click', { target: app.word });
  assert.equal(tip.hidden, true);
});

test('focused overflow handles scroll keys itself, clamps edges, and prevents page scrolling', () => {
  const app = setup(); select(app, true); const tip = app.tip();
  tip.clientHeight = 143;
  function press(key, expected) {
    let prevented = false;
    app.document.emit('keydown', { target: tip, key, preventDefault() { prevented = true; } });
    assert.equal(prevented, true, key + ' prevents native page scroll');
    assert.equal(tip.scrollTop, expected, key + ' clamps popup scroll');
    assert.equal(tip.hidden, false);
    assert.equal(app.document.activeElement, tip);
  }
  press('PageDown', 34);
  press('PageDown', 34);
  press('PageUp', 0);
  press('ArrowDown', 34);
  press('ArrowUp', 0);
  press('End', 34);
  press('Home', 0);
  press('Home', 0);
});

test('another mounted reader cannot handle the selected tooltip scroll key a second time', () => {
  const app = setup();
  app.wireRoot({ addEventListener() {}, contains() { return false; }, querySelectorAll() { return []; } });
  select(app, true);
  app.document.emit('keydown', { target: app.tip(), key: 'ArrowDown' });
  assert.equal(app.tip().scrollTop, 40);
});

test('page scroll clears hover and keyboard-preview highlights while preserving focus', () => {
  for (const keyboard of [false, true]) {
    const app = setup({hover:true});
    if (keyboard) {
      app.word.focus(); app.document.emit('keydown',{key:'Tab',target:app.word});
      app.root.emit('focusin',{target:app.word});
    } else app.root.emit('pointerover',{target:app.word});
    assert.equal(app.word.classList.contains('is-hi'),true);
    app.window.emit('scroll',{target:app.document});
    assert.equal(app.tip().hidden,true);
    assert.equal(app.word.classList.contains('is-hi'),false);
    assert.equal(app.linked.classList.contains('is-hi'),false);
    if (keyboard) assert.equal(app.document.activeElement,app.word);
    else {
      app.root.emit('pointerover',{target:app.word});
      assert.equal(app.tip().hidden,false);
    }
  }
});

test('hybrid touch contact cannot open a hover preview', () => {
  const app = setup({hover:true});
  app.root.emit('pointerover',{target:app.word,pointerType:'touch'});
  app.root.emit('mouseover',{target:app.word});
  assert.equal(app.word.classList.contains('is-hi'),false);
  select(app); assert.equal(app.word.classList.contains('is-hi'),true);
});
test('resize clears selected meaning and the next click opens immediately', () => {
  const app = setup(); select(app);
  app.window.emit('resize');
  assert.equal(app.tip().hidden,true);
  assert.equal(app.linked.classList.contains('is-hi'),false);
  select(app); assert.equal(app.tip().hidden,false);
});
