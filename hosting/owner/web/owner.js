const MAX_BYTES = 64 * 1024;
const encoder = new TextEncoder();

// A row counts songs containing the label, once per song. Coverage deliberately
// overlaps: it is never normalized into a partition or allocated across tags.
export function catalogueBreakdown(songs, field) {
  const counts = new Map();
  for (const song of songs) {
    const labels = [...new Set((song[field] || []).filter(label => typeof label === 'string' && label.trim()))];
    for (const label of labels.length ? labels : ['Unspecified']) counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts].map(([label, count]) => ({ label, count, coverage: count / songs.length * 100 }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
function validRequest(request) {
  return request && typeof request.id === 'string' && typeof request.text === 'string' &&
    Number.isFinite(Date.parse(request.createdAt)) &&
    ((request.status === 'queued' && request.completedAt === undefined) || (request.status === 'completed' &&
      Number.isFinite(Date.parse(request.completedAt)) && Date.parse(request.completedAt) >= Date.parse(request.createdAt)));
}
function formattedDate(value) {
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

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
  const controls = ['sign-in', 'setup-code', 'create-passkey', 'request-text', 'request-file', 'import-file', 'submit-request', 'refresh-requests', 'load-more', 'load-completed', 'sign-out'];
  let csrfToken = '';
  let busy = false;
  // Draft is the exact original file text until an input event edits it. Textarea
  // setters normalize CRLF; reading it back during submission would lose bytes.
  let draft = '';
  // An uncertain submission retains its UUID and text, including across sign-in.
  let pending = null;
  let requests = [];
  let visibleCount = 25;
  let completedVisibleCount = 25;
  let requestButtons = [];

  const status = message => { element('status').textContent = message; };
  function setBusy(value) {
    busy = value;
    for (const id of controls) element(id).disabled = value;
    for (const button of requestButtons) button.disabled = value;
    element('setup-form').setAttribute('aria-busy', String(value));
    element('request-form').setAttribute('aria-busy', String(value));
  }
  function signedOut() {
    csrfToken = '';
    requests = [];
    element('requests').replaceChildren();
    element('completed-requests').replaceChildren();
    element('language-chart').replaceChildren();
    element('subject-chart').replaceChildren();
    element('analytics-status').textContent = '';
    requestButtons = [];
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
    element('heading').textContent = 'Your library';
    element('queue-section').after(element('status'));
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
    if (authenticated && response.status === 401) signedOut();
    let data;
    try { data = await response.json(); } catch { throw new Error('The service could not complete this request. Please try again.'); }
    if (!response.ok) {
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
  function requestElement(request) {
    const details = doc.createElement('details'); details.className = 'request';
    const summary = doc.createElement('summary');
    const title = Array.from(request.text.split(/\r?\n/).find(line => line.trim()) || 'Song request').slice(0, 120).join('');
    summary.textContent = title;
    const date = doc.createElement('span'); date.className = 'request-date';
    date.textContent = request.status === 'completed'
      ? `Completed ${formattedDate(request.completedAt)} · Saved ${formattedDate(request.createdAt)}`
      : `Saved ${formattedDate(request.createdAt)} · Pending`;
    summary.append(date);
    const text = doc.createElement('pre'); text.textContent = request.text;
    details.append(summary, text);
    if (request.status === 'queued') {
      const button = doc.createElement('button'); button.type = 'button'; button.className = 'text-action complete-request';
      button.textContent = 'Mark completed'; button.disabled = busy;
      button.setAttribute('aria-label', `Mark request completed: ${title}`);
      button.addEventListener('click', () => completeRequest(request));
      requestButtons.push(button); details.append(button);
    }
    return details;
  }
  function renderRequests() {
    requestButtons = [];
    const queued = requests.filter(request => request.status === 'queued');
    const completed = requests.filter(request => request.status === 'completed');
    element('pending-heading').textContent = `${queued.length} pending request${queued.length === 1 ? '' : 's'}`;
    element('completed-heading').textContent = `${completed.length} completed request${completed.length === 1 ? '' : 's'}`;
    element('requests').replaceChildren();
    element('completed-requests').replaceChildren();
    if (!queued.length) {
      const empty = doc.createElement('p'); empty.className = 'empty'; empty.textContent = 'No pending requests.'; element('requests').append(empty);
    }
    for (const request of queued.slice(0, visibleCount)) element('requests').append(requestElement(request));
    for (const request of completed.slice(0, completedVisibleCount)) element('completed-requests').append(requestElement(request));
    element('completed-history').hidden = !completed.length;
    element('load-more').hidden = queued.length <= visibleCount;
    element('load-completed').hidden = completed.length <= completedVisibleCount;
  }
  async function completeRequest(request) {
    if (busy) return;
    setBusy(true); status('Marking request completed…');
    try {
      const result = await api('/api/requests/complete', { requestId: request.id }, true);
      const receipt = result.request;
      if (!validRequest(receipt) || receipt.status !== 'completed' || receipt.id !== request.id ||
          receipt.text !== request.text || receipt.createdAt !== request.createdAt) {
        throw new Error('Could not confirm completion. The request is still pending here; try again.');
      }
      requests = requests.map(item => item.id === receipt.id ? receipt : item);
      renderRequests();
      element('pending-heading').focus();
      status('Request marked completed. The original is saved in completed requests.');
    } catch (error) { status(error instanceof TypeError ? 'Could not confirm completion. Refresh or try again; the request is still shown here.' : errorMessage(error)); }
    finally { setBusy(false); }
  }
  async function refresh() {
    const data = await api('/api/requests', undefined, true);
    if (!Array.isArray(data.requests) || !data.requests.every(validRequest)) throw new Error('Could not load your requests. Please refresh.');
    requests = data.requests;
    renderRequests();
  }
  function renderBreakdown(target, rows) {
    const list = doc.createElement('ul'); list.className = 'breakdown-list';
    for (const row of rows) {
      const item = doc.createElement('li');
      const line = doc.createElement('div'); line.className = 'breakdown-label';
      const label = doc.createElement('span'); label.textContent = row.label;
      const value = doc.createElement('span'); value.className = 'breakdown-value';
      value.textContent = `${row.count} song${row.count === 1 ? '' : 's'} · ${row.coverage.toFixed(1)}%`;
      line.append(label, value);
      // SVG presentation attributes work under the existing strict style CSP.
      // Text above contains the entire meaning, so the graphic is decorative.
      const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 100 2'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('aria-hidden', 'true');
      const bar = doc.createElementNS('http://www.w3.org/2000/svg', 'rect');
      bar.setAttribute('width', String(row.coverage)); bar.setAttribute('height', '2'); bar.setAttribute('fill', 'currentColor');
      svg.append(bar); item.append(line, svg); list.append(item);
    }
    element(target).replaceChildren(list);
  }
  async function refreshCatalogue() {
    element('analytics-status').textContent = 'Loading the public library…';
    try {
      const data = await api('/api/catalogue', undefined, true);
      if (!Array.isArray(data.songs) || !Number.isFinite(Date.parse(data.fetchedAt)) ||
          !data.songs.every(song => song && typeof song.slug === 'string' && ['languageTags', 'subjectTags'].every(key =>
            song[key] === undefined || (Array.isArray(song[key]) && song[key].every(label => typeof label === 'string'))))) {
        throw new Error('Catalogue unavailable. Refresh to try again.');
      }
      if (!csrfToken) return;
      renderBreakdown('language-chart', catalogueBreakdown(data.songs, 'languageTags'));
      renderBreakdown('subject-chart', catalogueBreakdown(data.songs, 'subjectTags'));
      element('analytics-status').textContent = `${data.songs.length} song${data.songs.length === 1 ? '' : 's'} · Checked ${formattedDate(data.fetchedAt)}`;
    } catch (error) {
      element('language-chart').replaceChildren(); element('subject-chart').replaceChildren();
      if (csrfToken) element('analytics-status').textContent = 'Catalogue unavailable. Use Refresh to try again.';
      else status(errorMessage(error));
    }
  }
  async function refreshDashboard() {
    try { await refresh(); } catch (error) { status(errorMessage(error)); }
    if (csrfToken) await refreshCatalogue();
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
      await refreshDashboard();
    } catch (error) { status(errorMessage(error)); }
    finally { setBusy(false); if (csrfToken) element('pending-heading').focus(); }
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
      if (!validRequest(receipt) || receipt.id !== submission.requestId || receipt.text !== submission.text) {
        throw new Error('Could not confirm that this request was saved. Your draft is still here; try again.');
      }
      const unchanged = draft === submission.text;
      if (unchanged) { draft = ''; element('request-text').value = ''; countDraft(); }
      pending = null;
      const message = receipt.status === 'completed'
        ? (unchanged ? 'This request was already completed; it remains in completed requests.' : 'Earlier request was already completed. Your current draft is not submitted.')
        : (unchanged ? 'Saved to your pending requests.' : 'Earlier request saved. Your current draft is not submitted.');
      status(message);
      try { await refresh(); } catch (error) { status(`${message} ${errorMessage(error)}`); }
    } catch (error) { status(errorMessage(error)); }
    finally { setBusy(false); }
  });
  element('load-more').addEventListener('click', () => { visibleCount += 25; renderRequests(); });
  element('load-completed').addEventListener('click', () => { completedVisibleCount += 25; renderRequests(); });
  element('refresh-requests').addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    try { status(''); await refreshDashboard(); } catch (error) { status(errorMessage(error)); }
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
    status('');
    if (session.authenticated) { signedIn(session.csrfToken); await refreshDashboard(); }
  } catch (error) { status(errorMessage(error)); }
  finally { setBusy(false); }
}

if (typeof window !== 'undefined') mountOwner(window);
