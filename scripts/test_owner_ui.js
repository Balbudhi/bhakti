#!/usr/bin/env node
// Exercises the shipped owner client through its DOM event handlers. Native credential
// UI and HTTP are boundaries; these tests do not claim authenticator verification.
// Partitions: sign in/setup/cancel; exact text/import bounds; ambiguous retries/edit;
// expired authentication; saved-but-refresh-failed; hostile text rendered inertly.
// Visitors: counted/no history/quiet/failed/inconsistent; located and unlocated; range races.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.hidden = false; this.disabled = false; this._value = ''; this.textContent = ''; this.files = []; this.attributes = {}; this.style = {}; }
  get value() { return this._value; }
  set value(value) { this._value = String(value).replace(/\r\n?/g, '\n'); }
  set innerHTML(_) { throw new Error('Untrusted HTML rendering is forbidden'); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  async emit(type) { for (const callback of this.listeners[type] || []) await callback({ preventDefault() {} }); }
  append(...children) { this.children.push(...children); }
  after(element) { this.following = element; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  focus() { this.focused = true; }
  click() { return this.emit('click'); }
}
const ids = ['heading', 'auth', 'sign-in', 'setup', 'setup-form', 'setup-code', 'create-passkey', 'inbox', 'request-form', 'request-text', 'request-file', 'import-file', 'submit-request', 'byte-count', 'requests', 'load-more', 'refresh-requests', 'sign-out', 'status', 'pending-heading', 'completed-heading', 'completed-history', 'completed-requests', 'load-completed', 'analytics', 'analytics-status', 'language-chart', 'subject-chart', 'queue-section',
  'visitors', 'visitors-heading', 'visitors-status', 'visitor-detail', 'visitor-glance', 'visitor-points', 'figure-visitors', 'figure-first', 'figure-today', 'figure-countries', 'daily-max', 'daily-chart', 'daily-from', 'daily-readout', 'daily-rows', 'map-readout', 'country-list', 'city-list', 'more-countries', 'more-cities', 'range-7', 'range-30', 'range-90', 'range-400'];
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const bytes = (...values) => Uint8Array.from(values).buffer;
const assertion = () => ({ id: 'AQI', rawId: bytes(1, 2), type: 'public-key', authenticatorAttachment: 'cross-platform', response: { clientDataJSON: bytes(3, 4), authenticatorData: bytes(5, 6), signature: bytes(7, 8), userHandle: null }, getClientExtensionResults: () => ({}) });
let mountOwner, catalogueBreakdown, projectPlace, validVisitors;
async function fixture({ setup = false, authenticated = false, getCredential = async () => assertion(), createCredential, handler } = {}) {
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const requests = [];
  let nextID = 0;
  const credentials = { get: getCredential, create: createCredential };
  const env = {
    document: { getElementById: id => elements[id], createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag) },
    location: { pathname: setup ? '/setup' : '/' }, navigator: { credentials }, isSecureContext: true,
    crypto: { randomUUID: () => `00000000-0000-4000-8000-${String(++nextID).padStart(12, '0')}` },
    fetch: async (url, options = {}) => {
      const call = { url, ...options, body: options.body ? JSON.parse(options.body) : undefined };
      requests.push(call);
      const result = handler ? await handler(call) : undefined;
      if (result) return result;
      if (url === '/api/catalogue') return response({songs: [], fetchedAt: '2026-11-15T00:00:00Z'});
      if (url.startsWith('/api/visitors')) return response({ from: '2026-10-24', to: '2026-11-22', since: null, visitors: 0, firstTime: 0, daily: [], places: [], unlocated: 0 });
      if (url === '/api/session') return response(authenticated ? { authenticated: true, csrfToken: 'csrf' } : { authenticated: false });
      if (url === '/api/requests') return call.method === 'POST' ? response({ request: { id: call.body.requestId, text: call.body.text, status: 'queued', createdAt: '2026-01-01T00:00:00Z' } }) : response({ requests: [] });
      if (url.endsWith('/begin')) return response({ publicKey: { challenge: 'AQI', allowCredentials: [{ type: 'public-key', id: 'AwQ' }] }, challengeId: 'challenge' });
      if (url.endsWith('/finish')) return response({ authenticated: true, csrfToken: 'csrf' });
      return response({});
    },
  };
  await mountOwner(env);
  return { elements, requests, env };
}
async function edit(f, text) { f.elements['request-text'].value = text; await f.elements['request-text'].emit('input'); }
function collect(element) { return [element.textContent, ...element.children.map(collect)].join('\n'); }

(async () => {
  const source = fs.readFileSync(path.join(__dirname, '../hosting/owner/web/owner.js'), 'utf8');
  ({ mountOwner, catalogueBreakdown, projectPlace, validVisitors } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`));
  {
    const rows = catalogueBreakdown([
      {languageTags:['Hindi','Sanskrit','Hindi']}, {languageTags:['Hindi']},
      {}, {languageTags:['Sanskrit','Tamil']}, {languageTags:['Kannada']}
    ], 'languageTags');
    const expected = {Hindi:[2,40], Sanskrit:[2,40], Tamil:[1,20], Kannada:[1,20], Unspecified:[1,20]};
    assert.deepEqual(rows.map(row=>row.label).sort(),Object.keys(expected).sort());
    for (const row of rows) {
      assert.deepEqual([row.count, row.coverage], expected[row.label]);
    }
    assert.equal(rows.reduce((sum, row) => sum + row.coverage, 0), 140);
    assert.deepEqual(catalogueBreakdown([], 'subjectTags'), []);
  }
  {
    const f = await fixture({ getCredential: async () => { throw Object.assign(new Error(), { name: 'NotAllowedError' }); } });
    await f.elements['sign-in'].emit('click');
    assert.equal(f.requests.filter(r => r.url.endsWith('/finish')).length, 0);
    assert.match(f.elements.status.textContent, /cancel|not completed/i);
    assert.equal(f.elements['sign-in'].disabled, false);
  }
  {
    let options;
    const f = await fixture({ getCredential: async value => { options = value; return assertion(); } });
    await f.elements['sign-in'].emit('click');
    assert.deepEqual(Array.from(new Uint8Array(options.publicKey.challenge)), [1, 2]);
    assert.deepEqual(Array.from(new Uint8Array(options.publicKey.allowCredentials[0].id)), [3, 4]);
    const finish = f.requests.find(r => r.url === '/api/auth/finish');
    assert.equal(finish.body.challengeId, 'challenge');
    assert.equal(finish.body.credential.response.signature, 'Bwg');
    assert.equal(finish.body.credential.response.userHandle, null);
    assert.equal(f.elements.inbox.hidden, false);
    assert.equal(f.elements['pending-heading'].focused, true);
    assert.equal(f.elements['request-text'].focused, undefined);
    assert.equal(f.elements['queue-section'].following, f.elements.status);
  }
  {
    let options;
    const f = await fixture({ setup: true, createCredential: async value => { options = value; const c = assertion(); c.response = { clientDataJSON: bytes(3), attestationObject: bytes(4), getTransports: () => ['hybrid', 'internal'] }; return c; }, handler: call => call.url === '/api/setup/begin' ? response({ challengeId: 'registration', publicKey: { challenge: 'AQI', user: { id: 'AwQ', name: 'Owner', displayName: 'Owner' }, excludeCredentials: [{ id: 'BQY', type: 'public-key' }] } }) : undefined });
    f.elements['setup-code'].value = 'private-code';
    await f.elements['setup-form'].emit('submit');
    assert.deepEqual(Array.from(new Uint8Array(options.publicKey.user.id)), [3, 4]);
    assert.deepEqual(Array.from(new Uint8Array(options.publicKey.excludeCredentials[0].id)), [5, 6]);
    const finish = f.requests.find(r => r.url === '/api/setup/finish');
    assert.equal(finish.body.code, 'private-code');
    assert.equal(finish.body.credential.response.attestationObject, 'BA');
    assert.deepEqual(finish.body.credential.response.transports, ['hybrid', 'internal']);
    assert.equal(f.elements['setup-code'].value, '');
  }
  {
    let attempts = 0;
    const f = await fixture({ authenticated: true, handler: call => { if (call.url === '/api/requests' && call.method === 'POST') { if (++attempts === 1) throw new TypeError('Network error'); return response({ request: { id: call.body.requestId, text: call.body.text, status: 'queued', createdAt: '2026-01-01T00:00:00Z' } }); } } });
    const exact = '  Śrī राम\nhttps://example.test/<script>\n';
    await edit(f, exact);
    await f.elements['request-form'].emit('submit');
    assert.equal(f.elements['request-text'].value, exact);
    await f.elements['request-form'].emit('submit');
    const posts = f.requests.filter(r => r.method === 'POST');
    assert.equal(posts[0].body.requestId, posts[1].body.requestId);
    assert.equal(posts[1].body.text, exact);
    assert.equal(posts[1].headers['X-CSRF-Token'], 'csrf');
    assert.equal(f.elements['request-text'].value, '');
    assert.match(f.elements.status.textContent, /saved|queued/i);
  }
  {
    const f = await fixture({ authenticated: true, handler: call => call.method === 'POST' ? response({ error: 'Failed' }, 503) : undefined });
    await edit(f, 'first'); await f.elements['request-form'].emit('submit');
    await edit(f, 'second'); await f.elements['request-form'].emit('submit');
    const posts = f.requests.filter(r => r.method === 'POST');
    assert.notEqual(posts[0].body.requestId, posts[1].body.requestId);
    assert.equal(f.elements['request-text'].value, 'second');
  }
  {
    let expired = true;
    const f = await fixture({ authenticated: true, handler: call => { if (call.url === '/api/requests' && call.method === 'POST' && expired) { expired = false; return response({ error: 'Sign in again' }, 401); } } });
    await edit(f, 'preserve through sign-in'); await f.elements['request-form'].emit('submit');
    assert.equal(f.elements.auth.hidden, false);
    assert.equal(f.elements.inbox.hidden, true);
    await f.elements['sign-in'].emit('click');
    assert.equal(f.elements['request-text'].value, 'preserve through sign-in');
    assert.equal(f.elements.inbox.hidden, false);
    await f.elements['request-form'].emit('submit');
    const posts = f.requests.filter(r => r.url === '/api/requests' && r.method === 'POST');
    assert.equal(posts[0].body.requestId, posts[1].body.requestId);
  }
  {
    const f = await fixture({ authenticated: true });
    const raw = '\uFEFFŚrī\r\nराम\r\n';
    const fileBytes = new TextEncoder().encode(raw);
    f.elements['request-file'].files = [{ size: fileBytes.byteLength, arrayBuffer: async () => fileBytes.buffer }];
    await f.elements['request-file'].emit('change');
    assert.equal(f.elements['request-text'].value, raw.replace(/\r\n/g, '\n'));
    await f.elements['request-form'].emit('submit');
    assert.equal(f.requests.find(r => r.method === 'POST').body.text, raw);
  }
  {
    const f = await fixture({ authenticated: true }); await edit(f, 'keep');
    for (const file of [{ size: 2, arrayBuffer: async () => bytes(0xc3, 0x28) }, { size: 65537, arrayBuffer: async () => { throw new Error('Must reject before reading'); } }]) {
      f.elements['request-file'].files = [file]; await f.elements['request-file'].emit('change');
      assert.equal(f.elements['request-text'].value, 'keep');
      assert.match(f.elements.status.textContent, /UTF-8|64 KiB/i);
    }
    await edit(f, 'Ś'.repeat(32769)); await f.elements['request-form'].emit('submit');
    await edit(f, ' \n\t'); await f.elements['request-form'].emit('submit');
    assert.equal(f.requests.filter(r => r.method === 'POST').length, 0);
    await edit(f, 'a'.repeat(65536)); await f.elements['request-form'].emit('submit');
    assert.equal(f.requests.filter(r => r.method === 'POST').length, 1);
  }
  {
    const hostile = '<img src=x onerror=alert(1)>\n<script>bad()</script>';
    const f = await fixture({ authenticated: true, handler: call => call.url === '/api/requests' ? response({ requests: [{ id: 'id', text: hostile, status: 'queued', createdAt: '2026-01-01T00:00:00Z' }] }) : undefined });
    assert.ok(collect(f.elements.requests).includes(hostile));
  }
  {
    let saved = false;
    const f = await fixture({ authenticated: true, handler: call => { if (call.url !== '/api/requests') return; if (call.method === 'POST') { saved = true; return response({ request: { id: call.body.requestId, text: call.body.text, status: 'queued', createdAt: '2026-01-01T00:00:00Z' } }); } if (saved) return response({ error: 'Unavailable' }, 503); } });
    await edit(f, 'saved'); await f.elements['request-form'].emit('submit');
    assert.equal(f.elements['request-text'].value, '');
    assert.match(f.elements.status.textContent, /saved|queued/i);
  }
  {
    let release;
    const f = await fixture({ authenticated: true, handler: call => call.url === '/api/requests' && call.method === 'POST' ? new Promise(resolve => { release = () => resolve(response({ request: { id: call.body.requestId, text: call.body.text, status: 'queued', createdAt: '2026-01-01T00:00:00Z' } })); }) : undefined });
    await edit(f, 'in flight');
    const pending = f.elements['request-form'].emit('submit');
    assert.equal(f.elements['request-text'].disabled, true);
    assert.equal(f.elements['request-file'].disabled, true);
    assert.equal(f.elements['import-file'].disabled, true);
    await f.elements['request-form'].emit('submit');
    assert.equal(f.requests.filter(r => r.method === 'POST').length, 1);
    // A browser cannot edit disabled controls; also protect programmatic changes.
    await edit(f, 'newer draft');
    release(); await pending;
    assert.equal(f.elements['request-text'].value, 'newer draft');
    assert.match(f.elements.status.textContent, /current draft.*not|draft.*still/i);
  }
  for (const corrupt of [() => ({}), receipt => ({ request: { ...receipt, id: 'wrong' } }), receipt => ({ request: { ...receipt, text: 'wrong' } }), receipt => ({ request: { ...receipt, status: 'running' } }), receipt => ({ request: { ...receipt, completedAt: '2026-11-15T00:00:00Z' } }), receipt => ({ request: { ...receipt, createdAt: 'invalid' } })]) {
    const f = await fixture({ authenticated: true, handler: call => call.url === '/api/requests' && call.method === 'POST' ? response(corrupt({ id: call.body.requestId, text: call.body.text, status: 'queued', createdAt: '2026-01-01T00:00:00Z' })) : undefined });
    await edit(f, 'unconfirmed');
    await f.elements['request-form'].emit('submit');
    assert.equal(f.elements['request-text'].value, 'unconfirmed');
    await f.elements['request-form'].emit('submit');
    const posts = f.requests.filter(r => r.method === 'POST');
    assert.equal(posts[0].body.requestId, posts[1].body.requestId);
    assert.match(f.elements.status.textContent, /could not confirm/i);
  }
  {
    const f = await fixture();
    assert.equal(f.requests.some(r => r.url === '/api/catalogue'), false);
  }
  {
    const f = await fixture({authenticated:true, handler:call => call.url === '/api/catalogue' ? response({songs:[{slug:'one',languageTags:['<img onerror=bad()>'],subjectTags:[]}],fetchedAt:'2026-11-15T00:00:00Z'}) : undefined});
    assert.ok(collect(f.elements['language-chart']).includes('<img onerror=bad()>'));
    assert.ok(collect(f.elements['subject-chart']).includes('Unspecified'));
    assert.match(f.elements['analytics-status'].textContent,/1 song/);
  }
  {
    const f = await fixture({authenticated:true,handler:call => call.url === '/api/catalogue' ? response({error:'Catalogue unavailable'},503) : undefined});
    assert.match(f.elements['analytics-status'].textContent,/unavailable/i);
    assert.doesNotMatch(f.elements['analytics-status'].textContent,/0 songs/);
    assert.equal(f.elements.inbox.hidden,false);
    assert.match(f.elements['pending-heading'].textContent,/0 pending requests/i);
  }
  {
    const songs=Array.from({length:9},(_,i)=>({slug:'s'+i,languageTags:['Label '+i],subjectTags:[]}));
    const f=await fixture({authenticated:true,handler:call=>call.url==='/api/catalogue'?response({songs,fetchedAt:'2026-11-15T00:00:00Z'}):undefined});
    assert.doesNotMatch(collect(f.elements['language-chart']),/Other/);
    assert.equal(f.elements['language-chart'].children[0].children.length,9);
    for(let i=0;i<9;i++) assert.ok(collect(f.elements['language-chart']).includes('Label '+i));
  }
  const queued = {id:'request-id', text:'two songs\nhttps://example.test', status:'queued', createdAt:'2026-01-01T00:00:00Z'};
  const completed = {...queued, status:'completed', completedAt:'2026-11-15T00:00:00Z'};
  function completionButton(f) { return f.elements.requests.children[0].children.find(child => child.tagName === 'button'); }
  {
    let done = false;
    const f = await fixture({authenticated:true, handler:call => {
      if (call.url === '/api/requests/complete') { done = true; return response({request:completed}); }
      if (call.url === '/api/requests') return done ? response({error:'Unavailable'},503) : response({requests:[queued, {...completed,id:'older'}]});
    }});
    assert.match(f.elements['pending-heading'].textContent, /1 pending request/i);
    assert.match(f.elements['completed-heading'].textContent, /1 completed request/i);
    await completionButton(f).emit('click');
    const post = f.requests.find(r => r.url === '/api/requests/complete');
    assert.deepEqual(post.body, {requestId:queued.id});
    assert.equal(post.headers['X-CSRF-Token'],'csrf');
    assert.match(f.elements['pending-heading'].textContent,/0 pending requests/i);
    assert.equal(f.elements['pending-heading'].focused,true);
    await f.elements['refresh-requests'].emit('click');
    assert.match(f.elements['pending-heading'].textContent,/0 pending requests/i);
    assert.ok(collect(f.elements['completed-requests']).includes(queued.text));
  }
  for (const result of [() => {throw new TypeError('offline');}, () => response({request:{...completed,id:'wrong'}}), () => response({request:{...completed,text:'wrong'}}), () => response({request:{...completed,createdAt:'2026-02-01T00:00:00Z'}}), () => response({request:{...completed,completedAt:'invalid'}}), () => response({request:{...completed,status:'queued'}}), () => response({request:{...completed,status:'running'}}), () => response({request:{...completed,completedAt:'2025-12-01T00:00:00Z'}})]) {
    let tries = 0;
    const f = await fixture({authenticated:true,handler:call => {
      if (call.url === '/api/requests') return response({requests:[queued]});
      if (call.url === '/api/requests/complete') return ++tries === 1 ? result() : response({request:completed});
    }});
    await completionButton(f).emit('click');
    assert.match(f.elements['pending-heading'].textContent,/1 pending request/i);
    await completionButton(f).emit('click');
    assert.match(f.elements['pending-heading'].textContent,/0 pending requests/i);
    assert.deepEqual(f.requests.filter(r=>r.url==='/api/requests/complete').map(r=>r.body.requestId),[queued.id,queued.id]);
  }
  {
    const f = await fixture({authenticated:true,handler:call => call.url === '/api/requests' && call.method === 'POST' ? response({request:{...completed,id:call.body.requestId,text:call.body.text}}) : undefined});
    await edit(f,'already delivered'); await f.elements['request-form'].emit('submit');
    assert.equal(f.elements['request-text'].value,'');
    assert.match(f.elements.status.textContent,/already completed/i);
  }
  {
    let release;
    const f = await fixture({authenticated:true,handler:call => {
      if (call.url === '/api/requests') return response({requests:[queued]});
      if (call.url === '/api/requests/complete') return new Promise(resolve=>{ release=()=>resolve(response({error:'Sign in again'},401)); });
    }});
    const button=completionButton(f); const flight=button.emit('click');
    await button.emit('click');
    assert.equal(f.requests.filter(r=>r.url==='/api/requests/complete').length,1);
    assert.equal(button.disabled,true);
    release(); await flight;
    assert.equal(f.elements.requests.children.length,0);
    assert.equal(f.elements['completed-requests'].children.length,0);
    assert.equal(f.elements.inbox.hidden,true);
  }
  {
    const f = await fixture({authenticated:true,handler:call => {
      if (call.url === '/api/requests') return response({requests:[queued]});
      if (call.url === '/api/requests/complete') return {ok:false,status:401,json:async()=>{throw new SyntaxError('invalid JSON');}};
    }});
    await completionButton(f).emit('click');
    assert.equal(f.elements.requests.children.length,0);
    assert.equal(f.elements['completed-requests'].children.length,0);
    assert.equal(f.elements.inbox.hidden,true);
    assert.equal(f.elements.auth.hidden,false);
  }
  // Visitors. Every id used here must exist in the shipped page.
  {
    const html = fs.readFileSync(path.join(__dirname, '../hosting/owner/web/index.html'), 'utf8');
    for (const id of ids) assert.equal(html.split(`id="${id}"`).length, 2, `one #${id} in the owner page`);
    assert.match(html, /<a href="https:\/\/db-ip\.com"[^>]*>IP Geolocation by DB-IP<\/a>/);
    assert.doesNotMatch(html + source, / style="|setAttribute\('style'/, 'inline styles are blocked by the page policy');
  }
  {
    // The client projection must agree with the drawn land, in both viewBoxes.
    const svg = fs.readFileSync(path.join(__dirname, '../hosting/owner/web/world.svg'), 'utf8');
    assert.match(svg, /viewBox="40 0 920 429"/);
    assert.match(fs.readFileSync(path.join(__dirname, '../hosting/owner/web/index.html'), 'utf8'), /id="visitor-points" viewBox="40 0 920 429"/);
    const dots = []; let x = 0, y = 0;
    for (const [, kind, dx, dy] of svg.matchAll(/([Mm])([\d.]+) ([\d.]+)h0/g)) {
      if (kind === 'M') { x = +dx; y = +dy; } else x += +dx;
      dots.push([x, y]);
    }
    assert.ok(dots.length > 2000);
    const distance = (lat, lon) => { const p = projectPlace(lat, lon); return Math.min(...dots.map(([a, b]) => Math.hypot(a - p.x, b - p.y))); };
    for (const inland of [[28.6, 77.2], [21.1, 79.1], [39.1, -94.6], [-23.7, 133.9], [52.5, 13.4], [0.3, 32.6], [-15.8, -47.9], [35.7, 139.4]]) assert.ok(distance(...inland) < 7, `land at ${inland}`);
    for (const ocean of [[-30, 80], [30, -45], [10, -140], [-30, -15], [40, -30]]) assert.ok(distance(...ocean) > 30, `ocean at ${ocean}`);
    // Published Equal Earth extent: the equator spans 2.7066 radii each way.
    assert.ok(Math.abs(projectPlace(0, 180).x - 1000) < 1e-9 && Math.abs(projectPlace(0, 0).x - 500) < 1e-9);
  }
  const visitors = {
    from: '2026-10-24', to: '2026-11-22', since: '2026-11-20', visitors: 12, firstTime: 7, unlocated: 1,
    daily: [{ day: '2026-11-20', visitors: 9, firstTime: 5 }, { day: '2026-11-21', visitors: 0, firstTime: 0 }, { day: '2026-11-22', visitors: 4, firstTime: 2 }],
    places: [
      { country: 'IN', region: 'Maharashtra', city: 'Mumbai', lat: 19.1, lon: 72.9, visitors: 6 },
      { country: 'US', region: 'Massachusetts', city: '<b>Cambridge</b>', lat: 42.4, lon: -71.1, visitors: 3 },
      { country: 'IN', region: 'Delhi', city: 'Delhi', lat: 28.6, lon: 77.2, visitors: 1 },
      { country: 'SG', region: '', city: '', lat: 0, lon: 0, visitors: 1 },
    ],
  };
  const showing = (overrides = {}) => fixture({ authenticated: true, handler: call => call.url.startsWith('/api/visitors') ? response({ ...visitors, ...overrides }) : undefined });
  {
    const f = await showing();
    const text = id => f.elements[id].textContent;
    assert.deepEqual(f.requests.filter(r => r.url.startsWith('/api/visitors')).map(r => r.url), ['/api/visitors?days=30']);
    assert.deepEqual(['figure-visitors', 'figure-first', 'figure-today', 'figure-countries'].map(text), ['12', '7', '4', '3']);
    assert.equal(text('visitor-glance'), '4 visitors today');
    assert.equal(f.elements['visitor-glance'].hidden, false);
    assert.equal(f.elements['visitor-detail'].hidden, false);
    assert.equal(f.elements['visitor-detail'].attributes['aria-busy'], undefined);
    assert.match(text('visitors-status'), /Counting began on/);
    // Bars share the 9-visitor scale and a zero day stays a zero-height day.
    assert.deepEqual(f.elements['daily-chart'].children.map(day => day.children[0].style.height), ['100%', '0%', `${4 / 9 * 100}%`]);
    // Marks are styled before anyone points at them, and only one is highlighted.
    const classes = () => [...f.elements['daily-chart'].children, ...f.elements['visitor-points'].children].map(mark => mark.attributes.class);
    assert.deepEqual(classes(), ['day', 'day', 'day', 'place', 'place', 'place']);
    assert.equal(f.elements['daily-rows'].children.length, 3);
    assert.deepEqual(f.elements['daily-rows'].children[0].children.slice(1).map(cell => cell.textContent), ['4', '2']);
    assert.match(text('daily-readout'), /9 visitors/);
    await f.elements['daily-chart'].children[2].emit('click');
    assert.match(text('daily-readout'), /4 visitors, 2 new/);
    assert.deepEqual(classes().slice(0, 3), ['day', 'day', 'day shown']);
    f.elements['daily-chart'].onpointerleave();
    assert.match(text('daily-readout'), /Busiest day.*9 visitors/);
    // Three places have coordinates; circle area follows visitors.
    const points = f.elements['visitor-points'].children;
    assert.equal(points.length, 3);
    const radii = points.map(point => Number(point.children.find(child => child.attributes.class === 'halo').attributes.r));
    assert.ok(Math.abs((radii[0] / radii[1]) ** 2 - 2) < 0.02);
    assert.match(text('map-readout'), /^2 visitors could not be placed/);
    await points[0].emit('pointerenter');
    assert.match(text('map-readout'), /^Mumbai, Maharashtra, India: 6 visitors/);
    // Both lists account for all twelve visitors; hostile names stay text.
    const rows = id => f.elements[id].children[0].children.map(item => item.children[0].children.map(part => part.textContent));
    assert.deepEqual(rows('country-list').map(row => row[1]), ['7 visitors · 58.3%', '3 visitors · 25.0%', '1 visitor · 8.3%', '1 visitor · 8.3%']);
    assert.equal(rows('country-list')[0][0], 'India');
    assert.deepEqual(rows('city-list').map(row => row[0]), ['Mumbai, Maharashtra, India', '<b>Cambridge</b>, Massachusetts, United States', 'Delhi, India', 'Singapore, city unknown', 'Unknown place']);
    assert.equal(f.elements['more-cities'].hidden, true);
    // Signing out leaves no visitor data on the page.
    await f.elements['sign-out'].emit('click');
    assert.equal(f.elements['visitor-glance'].hidden, true);
    assert.equal(f.elements['visitor-detail'].hidden, true);
    for (const id of ['visitor-glance', 'visitor-points', 'city-list', 'country-list', 'daily-chart', 'daily-rows', 'figure-visitors', 'map-readout', 'visitors-status']) assert.equal(collect(f.elements[id]).trim(), '', id);
  }
  {
    // No history is not zero visitors; an empty recent window is.
    const none = await showing({ since: null, daily: [], places: [], visitors: 0, firstTime: 0, unlocated: 0 });
    assert.match(none.elements['visitors-status'].textContent, /No visits counted yet/);
    assert.equal(none.elements['visitor-detail'].hidden, true);
    assert.equal(none.elements['visitor-glance'].hidden, true);
    const quiet = await showing({ since: '2026-01-01', daily: [{ day: '2026-11-22', visitors: 0, firstTime: 0 }], places: [], visitors: 0, firstTime: 0, unlocated: 0 });
    assert.equal(quiet.elements['figure-visitors'].textContent, '0');
    assert.equal(quiet.elements['visitors-status'].textContent, '');
    assert.match(quiet.elements['daily-readout'].textContent, /No visitors/);
  }
  {
    const many = Array.from({ length: 11 }, (_, i) => ({ country: 'IN', region: 'R', city: `City ${i}`, lat: 20, lon: 78, visitors: 1 }));
    const f = await showing({ places: many });
    assert.equal(f.elements['city-list'].children[0].children.length, 8);
    assert.match(f.elements['more-cities'].textContent, /Show all 12 cities/);
    f.elements['more-cities'].onclick();
    assert.equal(f.elements['city-list'].children[0].children.length, 12);
    assert.equal(f.elements['more-cities'].hidden, true);
  }
  {
    // Any failed or inconsistent answer says unavailable, shows no zero, and leaves
    // the queue and the library breakdown working.
    const broken = { visitors: 13 };
    assert.equal(validVisitors(visitors), true);
    for (const bad of [{ ...visitors, ...broken }, { ...visitors, since: null }, { ...visitors, daily: [{ day: 'x', visitors: 1, firstTime: 0 }] }, { ...visitors, firstTime: -1 }, { ...visitors, places: [{ ...visitors.places[0], lat: 'x' }] }, null, {}]) assert.equal(validVisitors(bad), false);
    for (const answer of [() => response({ ...visitors, ...broken }), () => response({ error: 'no' }, 503), () => { throw new TypeError('offline'); }]) {
      const f = await fixture({ authenticated: true, handler: call => call.url.startsWith('/api/visitors') ? answer() : call.url === '/api/catalogue' ? response({ songs: [{ slug: 'a', languageTags: ['Hindi'], subjectTags: ['Kṛṣṇa'] }], fetchedAt: '2026-11-15T00:00:00Z' }) : undefined });
      assert.match(f.elements['visitors-status'].textContent, /unavailable/);
      assert.equal(f.elements['visitor-detail'].hidden, true);
      assert.equal(f.elements['figure-visitors'].textContent, '');
      assert.equal(f.elements['visitor-glance'].hidden, true);
      assert.match(f.elements['analytics-status'].textContent, /1 song/);
      assert.match(f.elements['pending-heading'].textContent, /0 pending/);
    }
  }
  {
    // The last chosen range wins even when an earlier answer arrives later.
    const waiting = {};
    const f = await fixture({ authenticated: true, handler: call => {
      const days = call.url.match(/visitors\?days=(\d+)/)?.[1];
      if (days === '30') return response(visitors);
      if (days) return new Promise(resolve => { waiting[days] = () => resolve(response({ ...visitors, firstTime: Number(days) === 90 ? 9 : 1 })); });
    } });
    const slow = f.elements['range-90'].emit('click');
    assert.equal(f.elements['visitor-detail'].attributes['aria-busy'], 'true');
    assert.equal(f.elements['figure-first'].textContent, '7', 'previous figures stay while loading');
    const fast = f.elements['range-7'].emit('click');
    waiting['7'](); await fast; waiting['90'](); await slow;
    assert.equal(f.elements['figure-first'].textContent, '1');
    assert.deepEqual([7, 30, 90, 400].map(days => f.elements[`range-${days}`].attributes['aria-pressed']), ['true', 'false', 'false', 'false']);
  }
  console.log('owner UI: authentication flow, exact import, safe rendering, and retry cases passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
