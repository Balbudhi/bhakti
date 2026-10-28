const MAX_BYTES = 64 * 1024;
const encoder = new TextEncoder();

function decodeBase64url(value) {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')), character => character.charCodeAt(0)).buffer;
}
function encodeBase64url(value) {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function credentialOptions(options, setup) {
  const result = { ...options, challenge: decodeBase64url(options.challenge) };
  if (setup) result.user = { ...options.user, id: decodeBase64url(options.user.id) };
  for (const key of ['allowCredentials', 'excludeCredentials']) {
    if (options[key]) result[key] = options[key].map(item => ({ ...item, id: decodeBase64url(item.id) }));
  }
  return result;
}
function serializeCredential(credential) {
  if (typeof credential.toJSON === 'function') return credential.toJSON();
  const response = { clientDataJSON: encodeBase64url(credential.response.clientDataJSON) };
  for (const key of ['attestationObject', 'authenticatorData', 'signature']) {
    if (credential.response[key]) response[key] = encodeBase64url(credential.response[key]);
  }
  if ('userHandle' in credential.response) response.userHandle = credential.response.userHandle ? encodeBase64url(credential.response.userHandle) : null;
  if (credential.response.getTransports) response.transports = credential.response.getTransports();
  return {
    id: credential.id, rawId: encodeBase64url(credential.rawId), type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    response, clientExtensionResults: credential.getClientExtensionResults(),
  };
}

export async function mountOwner(env) {
  const doc = env.document;
  const element = id => doc.getElementById(id);
  let setupView = /^\/setup\/?$/.test(env.location.pathname);
  const controls = ['sign-in', 'setup-code', 'create-passkey', 'request-text', 'request-file', 'import-file', 'submit-request', 'refresh-requests', 'sign-out'];
  let csrfToken = '';
  let busy = false;
  // Draft is the exact original file text until an input event edits it. Textarea
  // setters normalize CRLF; reading it back during submission would lose bytes.
  let draft = '';
  // An uncertain submission retains its UUID and text, including across sign-in.
  let pending = null;
  let requests = [];
  let visibleCount = 25;

  const status = message => { element('status').textContent = message; };
  function setBusy(value) {
    busy = value;
    for (const id of controls) element(id).disabled = value;
    element('setup-form').setAttribute('aria-busy', String(value));
    element('request-form').setAttribute('aria-busy', String(value));
  }
  function signedOut() {
    csrfToken = '';
    requests = [];
    element('requests').replaceChildren();
    element('inbox').hidden = true;
    element('auth').hidden = setupView;
    element('setup').hidden = !setupView;
    element('heading').textContent = setupView ? 'Create your passkey' : 'Owner';
    element(setupView ? 'setup-form' : 'sign-in').after(element('status'));
  }
  function signedIn(token) {
    if (typeof token !== 'string' || !token) throw new Error('Could not confirm sign-in. Please try again.');
    csrfToken = token;
    setupView = false;
    element('auth').hidden = true;
    element('setup').hidden = true;
    element('inbox').hidden = false;
    element('heading').textContent = 'Song requests';
    element('request-form').after(element('status'));
    element('setup-code').value = '';
  }
  async function api(url, body, authenticated = false) {
    const options = { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      options.method = 'POST';
      options.headers['Content-Type'] = 'application/json';
      if (authenticated) options.headers['X-CSRF-Token'] = csrfToken;
      options.body = JSON.stringify(body);
    }
    const response = await env.fetch(url, options);
    let data;
    try { data = await response.json(); } catch { throw new Error('The service could not complete this request. Please try again.'); }
    if (!response.ok) {
      if (authenticated && response.status === 401) signedOut();
      throw new Error(typeof data.error === 'string' ? data.error.slice(0, 300) : 'The request failed. Please try again.');
    }
    return data;
  }
  function errorMessage(error) {
    if (error.name === 'NotAllowedError' || error.name === 'AbortError') return 'Passkey sign-in was not completed. You can try again.';
    if (error instanceof TypeError) return 'Could not connect. Your draft is still here; try again.';
    return error.message || 'Could not complete this request. Please try again.';
  }
  function countDraft() {
    const count = encoder.encode(draft).byteLength;
    element('byte-count').textContent = `${(count / 1024).toFixed(count ? 1 : 0)} / 64 KiB`;
  }
  function renderRequests() {
    element('requests').replaceChildren();
    if (!requests.length) {
      const empty = doc.createElement('p'); empty.className = 'empty'; empty.textContent = 'No requests yet.'; element('requests').append(empty);
    }
    for (const request of requests.slice(0, visibleCount)) {
      const details = doc.createElement('details'); details.className = 'request';
      const summary = doc.createElement('summary');
      const title = request.text.split(/\r?\n/).find(line => line.trim()) || 'Song request';
      summary.textContent = Array.from(title).slice(0, 120).join('');
      const date = doc.createElement('span'); date.className = 'request-date';
      const created = new Date(request.createdAt);
      date.textContent = `${Number.isFinite(created.getTime()) ? created.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : ''} · Queued`;
      summary.append(date);
      const text = doc.createElement('pre'); text.textContent = request.text;
      details.append(summary, text); element('requests').append(details);
    }
    element('load-more').hidden = requests.length <= visibleCount;
  }
  async function refresh() {
    const data = await api('/api/requests', undefined, true);
    if (!Array.isArray(data.requests)) throw new Error('Could not load your requests. Please refresh.');
    requests = data.requests;
    renderRequests();
  }
  async function authenticate(setup) {
    if (busy) return;
    const method = setup ? 'create' : 'get';
    if (!env.isSecureContext || !env.navigator.credentials || typeof env.navigator.credentials[method] !== 'function') {
      status('Passkeys are unavailable here. Open this page in Safari or another browser that supports passkeys.'); return;
    }
    const code = element('setup-code').value;
    if (setup && !code) { status('Enter your one-time setup code.'); element('setup-code').focus(); return; }
    setBusy(true); status(setup ? 'Choose where to save your passkey…' : 'Use your passkey to sign in…');
    try {
      const prefix = setup ? '/api/setup' : '/api/auth';
      const begin = await api(`${prefix}/begin`, setup ? { code } : {});
      const credential = await env.navigator.credentials[method]({ publicKey: credentialOptions(begin.publicKey, setup) });
      if (!credential) throw new Error('Passkey sign-in was not completed. You can try again.');
      const body = { challengeId: begin.challengeId, credential: serializeCredential(credential) };
      if (setup) body.code = code;
      const result = await api(`${prefix}/finish`, body);
      signedIn(result.csrfToken);
      status('');
      try { await refresh(); } catch (error) { status(errorMessage(error)); }
    } catch (error) { status(errorMessage(error)); }
    finally { setBusy(false); if (csrfToken) element('request-text').focus(); }
  }

  element('sign-in').addEventListener('click', () => authenticate(false));
  element('setup-form').addEventListener('submit', event => { event.preventDefault(); return authenticate(true); });
  element('request-text').addEventListener('input', () => { draft = element('request-text').value; countDraft(); });
  element('import-file').addEventListener('click', () => { if (!busy) element('request-file').click(); });
  element('request-file').addEventListener('change', async () => {
    if (busy) return;
    const file = element('request-file').files[0];
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > MAX_BYTES) throw new Error('Choose a text file no larger than 64 KiB.');
      const buffer = await file.arrayBuffer();
      if (buffer.byteLength > MAX_BYTES) throw new Error('Choose a text file no larger than 64 KiB.');
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(buffer); }
      catch { throw new Error('This file is not valid UTF-8 text. Save it as UTF-8 and try again.'); }
      draft = text; element('request-text').value = text; countDraft(); status('Text loaded. Add it to the queue when ready.');
    } catch (error) { status(errorMessage(error)); }
    finally { element('request-file').value = ''; setBusy(false); }
  });
  element('request-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (!draft.trim()) { status('Add a song link, title, or note first.'); element('request-text').focus(); return; }
    if (encoder.encode(draft).byteLength > MAX_BYTES) { status('Keep each request within 64 KiB. Split longer notes into separate requests.'); return; }
    if (!csrfToken) { signedOut(); status('Sign in again. Your draft is still here.'); return; }
    if (!pending || pending.text !== draft) pending = { requestId: env.crypto.randomUUID(), text: draft };
    const submission = pending;
    setBusy(true); status('Saving…');
    try {
      const result = await api('/api/requests', submission, true);
      const receipt = result.request;
      if (!receipt || receipt.id !== submission.requestId || receipt.text !== submission.text || receipt.status !== 'queued' || !Number.isFinite(Date.parse(receipt.createdAt))) {
        throw new Error('Could not confirm that this request was saved. Your draft is still here; try again.');
      }
      const unchanged = draft === submission.text;
      if (unchanged) { draft = ''; element('request-text').value = ''; countDraft(); }
      pending = null;
      const message = unchanged ? 'Saved to your queue. Processing is not connected yet.' : 'Earlier request saved. Your current draft is not submitted.';
      status(message);
      try { await refresh(); } catch (error) { status(`${message} ${errorMessage(error)}`); }
    } catch (error) { status(errorMessage(error)); }
    finally { setBusy(false); }
  });
  element('load-more').addEventListener('click', () => { visibleCount += 25; renderRequests(); });
  element('refresh-requests').addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    try { await refresh(); status(''); } catch (error) { status(errorMessage(error)); }
    finally { setBusy(false); }
  });
  element('sign-out').addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    try { await api('/api/logout', {}, true); signedOut(); status(draft ? 'Signed out. Your unsent draft stays here until you close the page.' : 'Signed out.'); }
    catch (error) { status(errorMessage(error)); }
    finally { setBusy(false); }
  });
  signedOut(); setBusy(true);
  try {
    const session = await api('/api/session');
    if (session.authenticated) { signedIn(session.csrfToken); await refresh(); }
    status('');
  } catch (error) { status(errorMessage(error)); }
  finally { setBusy(false); }
}

if (typeof window !== 'undefined') mountOwner(window);
