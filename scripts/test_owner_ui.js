#!/usr/bin/env node
// Exercises the shipped owner client through its DOM event handlers. Native credential
// UI and HTTP are boundaries; these tests do not claim authenticator verification.
// Partitions: sign in/setup/cancel; exact text/import bounds; ambiguous retries/edit;
// expired authentication; saved-but-refresh-failed; hostile text rendered inertly.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.listeners = {}; this.hidden = false; this.disabled = false; this._value = ''; this.textContent = ''; this.files = []; this.attributes = {}; }
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
const ids = ['heading', 'auth', 'sign-in', 'setup', 'setup-form', 'setup-code', 'create-passkey', 'inbox', 'request-form', 'request-text', 'request-file', 'import-file', 'submit-request', 'byte-count', 'requests', 'load-more', 'refresh-requests', 'sign-out', 'status'];
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const bytes = (...values) => Uint8Array.from(values).buffer;
const assertion = () => ({ id: 'AQI', rawId: bytes(1, 2), type: 'public-key', authenticatorAttachment: 'cross-platform', response: { clientDataJSON: bytes(3, 4), authenticatorData: bytes(5, 6), signature: bytes(7, 8), userHandle: null }, getClientExtensionResults: () => ({}) });
let mountOwner;
async function fixture({ setup = false, authenticated = false, getCredential = async () => assertion(), createCredential, handler } = {}) {
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const requests = [];
  let nextID = 0;
  const credentials = { get: getCredential, create: createCredential };
  const env = {
    document: { getElementById: id => elements[id], createElement: tag => new Element(tag) },
    location: { pathname: setup ? '/setup' : '/' }, navigator: { credentials }, isSecureContext: true,
    crypto: { randomUUID: () => `00000000-0000-4000-8000-${String(++nextID).padStart(12, '0')}` },
    fetch: async (url, options = {}) => {
      const call = { url, ...options, body: options.body ? JSON.parse(options.body) : undefined };
      requests.push(call);
      const result = handler ? await handler(call) : undefined;
      if (result) return result;
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
  ({ mountOwner } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`));
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
    assert.equal(f.elements['request-form'].following, f.elements.status);
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
  for (const corrupt of [() => ({}), receipt => ({ request: { ...receipt, id: 'wrong' } }), receipt => ({ request: { ...receipt, text: 'wrong' } }), receipt => ({ request: { ...receipt, status: 'running' } }), receipt => ({ request: { ...receipt, createdAt: 'invalid' } })]) {
    const f = await fixture({ authenticated: true, handler: call => call.url === '/api/requests' && call.method === 'POST' ? response(corrupt({ id: call.body.requestId, text: call.body.text, status: 'queued', createdAt: '2026-01-01T00:00:00Z' })) : undefined });
    await edit(f, 'unconfirmed');
    await f.elements['request-form'].emit('submit');
    assert.equal(f.elements['request-text'].value, 'unconfirmed');
    await f.elements['request-form'].emit('submit');
    const posts = f.requests.filter(r => r.method === 'POST');
    assert.equal(posts[0].body.requestId, posts[1].body.requestId);
    assert.match(f.elements.status.textContent, /could not confirm/i);
  }
  console.log('owner UI: authentication flow, exact import, safe rendering, and retry cases passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
