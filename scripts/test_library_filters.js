#!/usr/bin/env node
"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const songs = [
  { slug: 'one', title: 'One', singer: 'Singer A', languageTags: ['Hindi'], subjectTags: ['Rāma'] },
  { slug: 'two', title: 'Two', singer: 'Singer B', languageTags: ['Hindi'], subjectTags: ['Śiva'] },
  { slug: 'three', title: 'Three', singer: 'Singer A', languageTags: ['Punjabi'], subjectTags: ['Śiva'] },
  { slug: 'four', title: 'Four', writer: 'Singer A', credit: 'Singer A', languageTags: ['Hindi'], subjectTags: ['Śiva'] },
];

function mount() {
  const filters = { listeners: {}, rows: [], buttons: [],
    addEventListener(type, handler) { this.listeners[type] = handler; },
    querySelectorAll(selector) { assert.equal(selector, '.tag-filter'); return this.buttons; },
    set innerHTML(html) {
      // Browser replacement discards old row scroll state and button identities.
      this.rows = [...html.matchAll(/<div\b[^>]*class="tag-row"[^>]*>(.*?)<\/div>/gs)].map(match => ({ html: match[1], scrollLeft: 0 }));
      this.buttons = [...html.matchAll(/<button\b([^>]*)>(.*?)<\/button>/gs)].map(match => {
        const attributes = Object.fromEntries([...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
        return { dataset: { kind: attributes['data-kind'], tag: attributes['data-tag'] },
          getAttribute(name) { return attributes[name]; },
          setAttribute(name, value) { attributes[name] = String(value); },
          closest(selector) { return selector === '.tag-filter' ? this : null; } };
      });
    },
  };
  const search = { value: '', listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
  let focused = null;
  const list = { listeners: {}, cards: [], addEventListener(type, fn) { this.listeners[type] = fn; },
    querySelector() { return this.cards.map(card => card.trigger).find(button => button.getAttribute('aria-expanded') === 'true') || null; },
    set innerHTML(html) {
      this.cards = [...html.matchAll(/<article class="song-card" data-song-slug="([^"]+)"/g)].map(match => {
        const slug = match[1];
        const panel = {hidden: true};
        const card = {querySelector: () => panel, panel};
        const button = (kind, position) => {
          const attrs = {'aria-expanded': 'false'};
          return {dataset: kind === 'trigger' ? {queueChoices: slug} : {addToQueue: slug, queuePosition: position},
            getAttribute: name => attrs[name], setAttribute: (name, value) => { attrs[name] = String(value); },
            focus() { focused = this; },
            closest(selector) {
              if (selector === '.song-card') return card;
              if (selector === '[data-queue-choices]' && kind === 'trigger') return this;
              if (selector === '[data-add-to-queue]' && kind === 'choice') return this;
              return null;
            }};
        };
        card.trigger = button('trigger'); card.next = button('choice', 'next'); card.end = button('choice', 'end');
        return card;
      });
    },
  };
  const root = {listeners: {}, events: [],
    querySelector: selector => ({ '#tagFilters': filters, '#songSearch': search, '#songList': list }[selector] || null),
    dispatchEvent(event) { this.events.push(event); },
    addEventListener(type, handler) { this.listeners[type] = handler; }};
  const context = { window: { BHAKTI_SONGS: songs }, document: {}, CustomEvent: class { constructor(type, detail) { Object.assign(this, { type }, detail); } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../assets/library.js'), 'utf8'), context);
  const controller = context.window.BHAKTI_LIBRARY.mount(root);
  const button = (kind, tag) => filters.buttons.find(b => b.dataset.kind === kind && b.dataset.tag === tag);
  const click = (kind, tag) => { const target = button(kind, tag); assert.ok(target, `${kind}:${tag} exists`); filters.listeners.click({ target }); };
  return { filters, search, controller, button, click, list, root, getFocused: () => focused, api: context.window.BHAKTI_SEARCH };
}

const visible = app => Array.from(app.controller.getVisibleSongs(), s => s.slug).sort();
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

test('singer is third independent facet; OR within a row, AND across rows and search', () => {
  const app = mount();
  assert.equal(app.filters.rows.length, 3);
  assert.match(app.filters.rows[2].html, /data-kind="singer"/);
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

test('playlist disclosure keeps one row open and choices restore focus without navigation', () => {
  const app = mount();
  const [first, second] = app.list.cards;
  app.list.listeners.click({target: first.trigger});
  assert.equal(first.panel.hidden, false);
  assert.equal(first.trigger.getAttribute('aria-expanded'), 'true');
  app.list.listeners.click({target: second.trigger});
  assert.equal(first.panel.hidden, true);
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
  app.root.listeners.click({target: {closest: () => second}});
  assert.equal(first.panel.hidden, true);
  app.list.listeners.click({target: first.trigger});
  app.root.listeners.click({target: {closest: () => null}});
  assert.equal(first.panel.hidden, true);
});
