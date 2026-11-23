#!/usr/bin/env node
"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');

const songs = [
  { slug: 'one', title: 'One', writer: 'Kabīr', singer: 'Singer A', languageTags: ['Hindi'], subjectTags: ['Rāma'] },
  { slug: 'two', title: 'Two', writer: 'Tulsīdās', singer: 'Singer B', languageTags: ['Hindi'], subjectTags: ['Śiva'] },
  { slug: 'three', title: 'Three', writer: 'Kabīr', singer: 'Singer A', languageTags: ['Punjabi'], subjectTags: ['Śiva'] },
  { slug: 'four', title: 'Four', writer: 'Singer A', credit: 'Singer A', languageTags: ['Hindi'], subjectTags: ['Śiva'] },
];

function mount(catalogue = songs, geometry = {}) {
  const { JSDOM } = require('jsdom');
  const dom = new JSDOM(`<main><button id="filterToggle" aria-expanded="false"></button>
    <span id="filterCount"></span><div id="tagFilters" hidden></div>
    <input id="songSearch"><div id="songList"></div></main>`, {runScripts: 'outside-only'});
  const { window } = dom;
  const { document } = window;
  window.BHAKTI_SONGS = catalogue;
  window.innerWidth = 390; window.innerHeight = 844;
  const documentEvents = {}, windowEvents = {};
  const captureListeners = (target, listeners = {}) => {
    const add = target.addEventListener.bind(target);
    target.addEventListener = (type, handler, options) => {
      listeners[type] = handler; add(type, handler, options);
    };
    target.listeners = listeners;
  };
  captureListeners(document, documentEvents); captureListeners(window, windowEvents);
  const root = document.querySelector('main');
  const filters = root.querySelector('#tagFilters');
  const search = root.querySelector('#songSearch');
  const list = root.querySelector('#songList');
  const filterToggle = root.querySelector('#filterToggle');
  const filterCount = root.querySelector('#filterCount');
  for (const target of [root, filters, search, list, filterToggle]) captureListeners(target);
  root.events = [];
  const dispatch = root.dispatchEvent.bind(root);
  root.dispatchEvent = event => { root.events.push(event); return dispatch(event); };
  window.HTMLElement.prototype.getBoundingClientRect = function() {
    if (this.matches('.song-queue-actions')) return {width: 184, height: 96};
    return geometry.anchor || {top: 500, bottom: 542, right: 374};
  };
  if (geometry.player) {
    const original = document.getElementById.bind(document);
    document.getElementById = id => id === 'audioPlayer' ? geometry.player : original(id);
  }
  window.eval(fs.readFileSync(path.join(__dirname, '../assets/library.js'), 'utf8'));
  const controller = window.BHAKTI_LIBRARY.mount(root);
  Object.defineProperty(filters, 'rows', {get: () => [...filters.querySelectorAll('.tag-row')].map(row => {
    row.html = row.innerHTML;
    return row;
  })});
  Object.defineProperty(filters, 'buttons', {get: () => [...filters.querySelectorAll('.tag-filter')]});
  Object.defineProperty(list, 'html', {get: () => list.innerHTML});
  Object.defineProperty(list, 'cards', {get: () => [...list.querySelectorAll('.song-card')].map(card => {
    card.trigger = card.querySelector('[data-queue-choices]');
    // Accommodate both the baseline per-row menu and the shared replacement.
    const panel = card.querySelector('.song-queue-actions') || list.querySelector('.song-queue-actions');
    card.panel = panel;
    card.next = panel.querySelector('[data-queue-position="next"]');
    card.end = panel.querySelector('[data-queue-position="end"]');
    return card;
  })});
  const button = (kind, tag) => filters.buttons.find(b => b.dataset.kind === kind && b.dataset.tag === tag);
  const click = (kind, tag) => { const target = button(kind, tag); assert.ok(target, `${kind}:${tag} exists`); target.click(); };
  return { filters, search, controller, button, click, list, root, filterToggle, filterCount,
    documentEvents, windowEvents, getFocused: () => document.activeElement, api: window.BHAKTI_SEARCH };
}

test('a library row says who wrote and who sang', () => {
  const { creditLine } = mount().api;
  assert.equal(creditLine({writer: 'Tulsīdās', singer: 'Hari Om Sharan'}), 'By Tulsīdās · sung by Hari Om Sharan');
  assert.equal(creditLine({writer: '', singer: 'Maninder Ji'}), 'Sung by Maninder Ji');
  assert.equal(creditLine({writer: 'Kabīr', singer: ''}), 'By Kabīr');
  assert.equal(creditLine({writer: 'X', singer: 'X'}), 'Written and sung by X');
  assert.equal(creditLine({writer: 'Vyāsa', ensemble: 'Bhawan'}), 'By Vyāsa · sung at Bhawan');
  assert.equal(creditLine({ensemble: 'Bhawan'}), 'Sung at Bhawan');
  assert.equal(creditLine({credit: ''}), '');
});
const visible = app => Array.from(app.controller.getVisibleSongs(), s => s.slug).sort();
test('compact filter toggle preserves controls and selection while closing and reopening', () => {
  const app = mount(); const rows = app.filters.rows;
  app.filterToggle.listeners.click();
  assert.equal(app.filters.hidden, false);
  assert.equal(app.filterToggle.getAttribute('aria-expanded'), 'true');
  app.click('language','Hindi');
  app.filterToggle.listeners.click();
  assert.equal(app.filters.hidden, true);
  assert.equal(app.filterCount.textContent,'1');
  app.filterToggle.listeners.click();
  assert.deepEqual(app.filters.rows,rows);
  assert.equal(app.button('language','Hindi').getAttribute('aria-pressed'),'true');
});
test('action popover focuses its commands and supports arrow keys, Escape and outside focus', () => {
  const app = mount(); const first = app.list.cards[0];
  app.list.listeners.click({target:first.trigger});
  assert.equal(app.getFocused(),first.next);
  assert.equal(first.panel.style.left,'190px');
  app.list.listeners.keydown({target:first.next,key:'ArrowDown',preventDefault(){}});
  assert.equal(app.getFocused(),first.end);
  app.list.listeners.keydown({target:first.end,key:'ArrowDown',preventDefault(){}});
  assert.equal(app.getFocused(),first.next);
  app.list.listeners.keydown({target:first.next,key:'Escape',preventDefault(){}});
  assert.equal(first.panel.hidden,true);
  assert.equal(app.getFocused(),first.trigger);
  app.list.listeners.click({target:first.trigger});
  app.documentEvents.focusin({target:{closest:()=>null}});
  assert.equal(first.panel.hidden,true);
});
test('navigation and viewport changes dismiss cached library menus', () => {
  const app = mount(); const first = app.list.cards[0];
  for (const event of ['popstate', 'bhakti:song-change', 'scroll', 'resize']) {
    app.list.listeners.click({target:first.trigger});
    assert.equal(first.panel.hidden,false);
    assert.equal(typeof app.windowEvents[event], 'function', `${event} has a dismissal handler`);
    app.windowEvents[event]();
    assert.equal(first.panel.hidden,true);
    assert.equal(first.trigger.getAttribute('aria-expanded'),'false');
  }
});
test('popover stays above the player even when its trigger is partly obscured', () => {
  const app = mount(songs, {
    anchor: {top:740, bottom:782, right:374},
    player: {hidden:false, getBoundingClientRect:()=>({top:700})},
  });
  const first = app.list.cards[0];
  app.list.listeners.keydown({target:first.trigger,key:'ArrowDown',preventDefault(){}});
  assert.ok(parseFloat(first.panel.style.top) >= 8);
  assert.ok(parseFloat(first.panel.style.top) + 96 <= 692);
  assert.equal(app.getFocused(),first.next);
});
test('collapsed filter summary identifies retained choices and empty search has recovery guidance', () => {
  const app = mount();
  assert.equal(app.filterCount.hidden, true);
  app.click('subject', 'Śiva');
  app.click('language', 'Hindi');
  assert.equal(app.filterCount.textContent, '2');
  assert.match(app.filterToggle.title, /Śiva · Hindi/);
  app.search.value = 'no such song'; app.search.listeners.input();
  assert.deepEqual(visible(app), []);
  assert.match(app.list.html, /No songs match/);
  assert.match(app.list.html, /search or filters/);
  assert.equal(app.filterCount.textContent, '2');
  app.click('all-subjects', 'All'); app.click('all-languages', 'All');
  assert.equal(app.filterCount.hidden, true);
});
test('scrolled filter activation and search preserve row/button identity and selected state', () => {
  const app = mount();
  const row = app.filters.rows[0];
  row.scrollLeft = 180;
  const pressed = app.button('subject', 'Śiva');
  app.click('subject', 'Śiva');
  assert.equal(app.filters.rows[0], row);
  assert.equal(row.scrollLeft, 180);
  assert.equal(app.button('subject', 'Śiva'), pressed);
  assert.equal(pressed.getAttribute('aria-pressed'), 'true');
  assert.equal(app.button('subject', 'Rāma').getAttribute('aria-pressed'), 'false');
  app.search.value = 'Two'; app.search.listeners.input();
  assert.equal(app.filters.rows[0], row);
  assert.equal(app.button('subject', 'Śiva'), pressed);
});

test('singer follows poet facet; OR within a row, AND across rows and search', () => {
  const app = mount();
  assert.equal(app.filters.rows.length, 4);
  assert.match(app.filters.rows[3].html, /data-kind="singer"/);
  app.click('singer', 'Singer A');
  assert.deepEqual(visible(app), ['one', 'three']);
  app.click('subject', 'Śiva');
  assert.deepEqual(visible(app), ['three']);
  app.click('singer', 'Singer B');
  assert.deepEqual(visible(app), ['three', 'two']);
  app.click('language', 'Hindi');
  assert.deepEqual(visible(app), ['two']);
  app.click('all-singers', 'All');
  assert.deepEqual(visible(app), ['four', 'two']);
  assert.equal(app.button('subject', 'Śiva').getAttribute('aria-pressed'), 'true');
  assert.equal(app.button('language', 'Hindi').getAttribute('aria-pressed'), 'true');
  app.search.value = 'Four'; app.search.listeners.input();
  assert.deepEqual(visible(app), ['four']);
});

test('pure singer filter never treats writer/credit as singer, and empty resets', () => {
  const { api } = mount();
  assert.deepEqual(Array.from(api.filterSongs(songs, { singers: ['Singer A'] }), s => s.slug), ['one', 'three']);
  assert.equal(api.filterSongs(songs, { singers: [] }).length, 4);
  assert.equal(api.filterSongs(songs, { singers: ['Unknown'] }).length, 0);
  assert.equal(api.matchesSearch(songs[1], 'Singer B'), true);
});

test('poets sit above singers with independent OR choices and an All reset', () => {
  const app = mount();
  assert.match(app.filters.rows[2].html, /data-kind="poet"/);
  assert.match(app.filters.rows[3].html, /data-kind="singer"/);
  const row = app.filters.rows[2]; row.scrollLeft = 120;
  const button = app.button('poet', 'Kabīr');
  app.click('poet', 'Kabīr');
  assert.deepEqual(visible(app), ['one', 'three']);
  app.click('poet', 'Tulsīdās');
  assert.deepEqual(visible(app), ['one', 'three', 'two']);
  app.click('subject', 'Śiva');
  app.click('singer', 'Singer A');
  assert.deepEqual(visible(app), ['three']);
  app.click('all-poets', 'All');
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  assert.equal(app.button('all-poets', 'All').getAttribute('aria-pressed'), 'true');
  assert.equal(app.button('singer', 'Singer A').getAttribute('aria-pressed'), 'true');
  assert.deepEqual(visible(app), ['three']);
  assert.equal(app.filters.rows[2], row);
  assert.equal(row.scrollLeft, 120);
  assert.equal(app.button('poet', 'Kabīr'), button);
});

test('poet choices use writer only and folded search includes poet names', () => {
  const { api, button } = mount();
  assert.deepEqual(Array.from(api.filterSongs(songs, { poets: ['Singer A'] }), s => s.slug), ['four']);
  assert.equal(api.filterSongs(songs, { poets: [] }).length, 4);
  assert.equal(api.filterSongs(songs, { poets: ['Unknown'] }).length, 0);
  assert.equal(button('poet', 'Singer B'), undefined);
  assert.equal(api.matchesSearch(songs[0], 'Kabir'), true);
  assert.deepEqual(Array.from(api.filterSongs(songs, { poets: ['Kabīr'], languages: ['Hindi'], query: 'One' }), s => s.slug), ['one']);
});

test('named poets in composite credits share facets with solo poems', () => {
  const writers = ['Kabīr', 'Gurū Arjan · Gurū Rām Dās · Kabīr', 'Kabīr and other poets',
    'Kabīr, Nānak & others', 'Sant Tukaram; Sant Janabai', 'Kishore Gagare & Jayshree Medhi', 'Traditional', '  '];
  const catalogue = writers.map((writer, index) => ({slug: String(index), title: String(index), writer,
    languageTags: [], subjectTags: []}));
  const app = mount(catalogue);
  app.click('poet', 'Kabīr');
  assert.deepEqual(visible(app), ['0', '1', '2', '3']);
  assert.ok(app.button('poet', 'Gurū Arjan'));
  assert.ok(app.button('poet', 'Gurū Rām Dās'));
  assert.ok(app.button('poet', 'Nānak'));
  assert.ok(app.button('poet', 'Sant Janabai'));
  assert.ok(app.button('poet', 'Kishore Gagare'));
  assert.ok(app.button('poet', 'Jayshree Medhi'));
  for (const tag of ['others', 'other poets', 'Traditional', '', writers[1]]) {
    assert.equal(app.button('poet', tag), undefined);
  }
  assert.equal(app.filters.buttons.filter(button => button.dataset.kind === 'poet' && button.dataset.tag === 'Kabīr').length, 1);
  assert.deepEqual(catalogue.map(song => song.writer), writers);
});

test('playlist disclosure keeps one row open and choices restore focus without navigation', () => {
  const app = mount();
  const [first, second] = app.list.cards;
  app.list.listeners.click({target: first.trigger});
  assert.equal(first.panel.hidden, false);
  assert.equal(first.trigger.getAttribute('aria-expanded'), 'true');
  app.list.listeners.click({target: second.trigger});
  assert.equal(first.trigger.getAttribute('aria-expanded'), 'false');
  assert.equal(second.panel.hidden, false);
  for (const choice of [second.next, second.end]) {
    if (second.panel.hidden) app.list.listeners.click({target: second.trigger});
    app.list.listeners.click({target: choice});
    assert.equal(second.panel.hidden, true);
    assert.equal(app.getFocused(), second.trigger);
    const event = app.root.events.at(-1);
    assert.equal(event.type, 'bhakti:add-to-queue');
    assert.equal(event.detail.position, choice.dataset.queuePosition);
    assert.equal(event.detail.song.slug, choice.dataset.addToQueue);
  }
});

test('playlist Escape returns focus and a click outside the open row dismisses it', () => {
  const app = mount();
  const [first, second] = app.list.cards;
  app.list.listeners.click({target: first.trigger});
  app.list.listeners.keydown({key: 'Escape', target: first.next});
  assert.equal(first.panel.hidden, true);
  assert.equal(app.getFocused(), first.trigger);
  app.list.listeners.click({target: first.trigger});
  app.documentEvents.click({target: {closest: () => null}});
  assert.equal(first.panel.hidden, true);
  app.list.listeners.click({target: first.trigger});
  app.documentEvents.click({target: {closest: () => null}});
  assert.equal(first.panel.hidden, true);
});

test('search and filter changes preserve catalogue row identity', () => {
  const app = mount();
  const original = app.list.cards.slice();
  app.search.value = 'One'; app.search.listeners.input();
  app.search.value = ''; app.search.listeners.input();
  assert.equal(app.list.cards.length, original.length);
  for (let i = 0; i < original.length; i++) assert.equal(app.list.cards[i], original[i]);
});

test('one shared menu targets the selected row without multiplying hidden controls', () => {
  const app = mount();
  assert.equal(app.list.querySelectorAll('[role="menu"]').length, 1);
  assert.equal(app.list.querySelectorAll('[role="menuitem"]').length, 2);
  const [first, second] = app.list.cards;
  first.trigger.click();
  second.trigger.click();
  assert.equal(first.trigger.getAttribute('aria-expanded'), 'false');
  second.next.click();
  const event = app.root.events.at(-1);
  assert.equal(event.type, 'bhakti:add-to-queue');
  assert.equal(event.detail.song.slug, second.dataset.songSlug);
  assert.equal(event.detail.position, 'next');
  assert.equal(app.getFocused(), second.trigger);
});

test('retained rows expose exactly the filtered order and empty search hides every row', () => {
  const app = mount();
  const rendered = () => [...app.list.querySelectorAll('.song-card:not([hidden])')].map(card => card.dataset.songSlug);
  const expected = () => Array.from(app.controller.getVisibleSongs(), song => song.slug);
  for (const query of ['One', 'Singer A', 'does not exist', '']) {
    app.search.value = query; app.search.dispatchEvent(new app.search.ownerDocument.defaultView.Event('input'));
    assert.deepEqual(rendered(), expected());
    assert.equal(app.list.querySelector('.library-empty').hidden, expected().length > 0);
  }
});
