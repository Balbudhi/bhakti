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

// Equal Earth, with the constants and viewBox of web/world.svg (build_world.py).
const EARTH = { scale: 184.73156767339816, top: 1.2882111962202532, a1: 1.340264, a2: -0.081106, a3: 0.000893, a4: 0.003796, m: Math.sqrt(3) / 2 };
export function projectPlace(latitude, longitude) {
  const { scale, top, a1, a2, a3, a4, m } = EARTH;
  const theta = Math.asin(m * Math.sin(latitude * Math.PI / 180));
  const square = theta * theta;
  const sixth = square * square * square;
  const x = longitude * Math.PI / 180 * Math.cos(theta) / (m * (a1 + 3 * a2 * square + sixth * (7 * a3 + 9 * a4 * square)));
  return { x: 500 + x * scale, y: (top - theta * (a1 + a2 * square + sixth * (a3 + a4 * square))) * scale };
}
const isCount = value => Number.isSafeInteger(value) && value >= 0;
const isDay = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value));
export function validVisitors(data) {
  return Boolean(data) && isDay(data.from) && isDay(data.to) && (data.since === null || isDay(data.since)) &&
    [data.visitors, data.firstTime, data.unlocated].every(isCount) && Array.isArray(data.daily) && Array.isArray(data.places) &&
    (data.since === null) === !data.daily.length &&
    data.daily.every(row => row && isDay(row.day) && isCount(row.visitors) && isCount(row.firstTime) && row.firstTime <= row.visitors) &&
    data.places.every(row => row && [row.country, row.region, row.city].every(value => typeof value === 'string') && row.country &&
      isCount(row.visitors) && Math.abs(row.lat) <= 90 && Math.abs(row.lon) <= 180) &&
    data.places.reduce((sum, row) => sum + row.visitors, data.unlocated) === data.visitors;
}
function countryName(code) {
  try { return new Intl.DisplayNames(undefined, { type: 'region' }).of(code) || code; } catch { return code; }
}
// Every visitor appears in exactly one row, so each list adds up to all visitors.
export function visitorPlaces(data) {
  const row = (label, count) => ({ label, count, coverage: count / data.visitors * 100 });
  const countries = new Map();
  for (const item of data.places) countries.set(item.country, (countries.get(item.country) || 0) + item.visitors);
  const unknown = data.unlocated ? [row('Unknown place', data.unlocated)] : [];
  return {
    countryCount: countries.size,
    countries: [...[...countries].sort((a, b) => b[1] - a[1]).map(([code, count]) => row(countryName(code), count)), ...unknown],
    cities: [...data.places.map(item => row(placeName(item), item.visitors)), ...unknown],
  };
}
function placeName(item) {
  const country = countryName(item.country);
  return item.city ? [item.city, item.region !== item.city && item.region, country].filter(Boolean).join(', ') : `${item.region || country}, city unknown`;
}
function plural(count, noun) { return `${count.toLocaleString()} ${noun}${count === 1 ? '' : 's'}`; }
function dayLabel(day) {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
    timeZone: 'UTC', day: 'numeric', month: 'long', ...(day.slice(0, 4) !== String(new Date().getFullYear()) && { year: 'numeric' }),
  });
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
  const RANGES = [7, 30, 90, 400];
  const LISTED_PLACES = 8;
  let visitorRange = 30;
  let visitorLoad = 0; // Only the latest load may render; sign-out invalidates all.

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
    visitorLoad++;
    clearVisitors();
    element('visitors-status').textContent = '';
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
  function renderBreakdown(target, rows, noun = 'song') {
    const list = doc.createElement('ul'); list.className = 'breakdown-list';
    for (const row of rows) {
      const item = doc.createElement('li');
      const line = doc.createElement('div'); line.className = 'breakdown-label';
      const label = doc.createElement('span'); label.textContent = row.label;
      const value = doc.createElement('span'); value.className = 'breakdown-value';
      value.textContent = `${plural(row.count, noun)} · ${row.coverage.toFixed(1)}%`;
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
  function clearVisitors() {
    for (const id of ['daily-chart', 'visitor-points', 'country-list', 'city-list', 'daily-rows']) element(id).replaceChildren();
    for (const id of ['figure-visitors', 'figure-first', 'figure-today', 'figure-countries', 'daily-max', 'daily-from', 'daily-readout', 'map-readout']) element(id).textContent = '';
    element('visitor-detail').hidden = true;
    element('visitor-detail').removeAttribute('aria-busy');
    element('visitor-glance').hidden = true;
    element('visitor-glance').textContent = '';
  }
  function svgElement(tag, attributes) {
    const result = doc.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [name, value] of Object.entries(attributes)) result.setAttribute(name, String(value));
    return result;
  }
  // Pointing at or tapping a mark shows its value; leaving restores the summary.
  function describeMarks(container, readout, summary, marks) {
    let shown = null;
    const show = mark => {
      if (shown) shown.node.setAttribute('class', shown.name);
      shown = mark;
      if (mark) mark.node.setAttribute('class', `${mark.name} shown`);
      element(readout).textContent = mark ? mark.text : summary;
    };
    for (const mark of marks) {
      mark.node.setAttribute('class', mark.name);
      for (const type of ['pointerenter', 'click']) mark.node.addEventListener(type, () => show(mark));
    }
    container.onpointerleave = () => show(null);
    show(null);
  }
  function renderDaily(days) {
    const chart = element('daily-chart');
    const largest = Math.max(...days.map(row => row.visitors));
    const busiest = days.find(row => row.visitors === largest);
    const summary = largest ? `Busiest day: ${dayLabel(busiest.day)}, ${plural(largest, 'visitor')}.` : 'No visitors in this period.';
    const marks = days.map(row => {
      const node = doc.createElement('div');
      const bar = doc.createElement('span');
      // CSSOM assignment is permitted by the strict style policy.
      bar.style.height = `${largest ? row.visitors / largest * 100 : 0}%`;
      node.append(bar);
      return { node, name: 'day', text: `${dayLabel(row.day)}: ${plural(row.visitors, 'visitor')}, ${row.firstTime.toLocaleString()} new.` };
    });
    chart.className = days.length > 100 ? 'daily-chart dense' : 'daily-chart';
    chart.replaceChildren(...marks.map(mark => mark.node));
    chart.setAttribute('aria-label', `Visitors each day. ${summary} Every day is listed under Daily numbers.`);
    element('daily-max').textContent = largest.toLocaleString();
    element('daily-from').textContent = days.length > 1 ? dayLabel(days[0].day) : '';
    describeMarks(chart, 'daily-readout', summary, marks);
    element('daily-rows').replaceChildren(...[...days].reverse().map(row => {
      const line = doc.createElement('tr');
      for (const text of [dayLabel(row.day), row.visitors.toLocaleString(), row.firstTime.toLocaleString()]) {
        const cell = doc.createElement('td'); cell.textContent = text; line.append(cell);
      }
      return line;
    }));
  }
  function renderMap(data) {
    const located = data.places.filter(item => item.lat || item.lon).sort((a, b) => b.visitors - a.visitors);
    const largest = Math.max(1, ...located.map(item => item.visitors));
    const mapped = located.reduce((sum, item) => sum + item.visitors, 0);
    const marks = located.map(item => {
      const { x, y } = projectPlace(item.lat, item.lon);
      // Area, not radius, is proportional to visitors.
      const radius = Math.max(5, 30 * Math.sqrt(item.visitors / largest));
      const at = { cx: x.toFixed(1), cy: y.toFixed(1) };
      const node = svgElement('g', {});
      const title = svgElement('title', {});
      const text = `${placeName(item)}: ${plural(item.visitors, 'visitor')}`;
      title.textContent = text;
      node.append(title, svgElement('circle', { ...at, r: radius.toFixed(1), class: 'halo' }),
        svgElement('circle', { ...at, r: 4.5, class: 'core' }), svgElement('circle', { ...at, r: Math.max(16, radius).toFixed(1), class: 'hit' }));
      return { node, name: 'place', text: `${text}.` };
    });
    element('visitor-points').replaceChildren(...marks.map(mark => mark.node));
    const missing = data.visitors - mapped;
    describeMarks(element('visitor-points'), 'map-readout', missing ? `${plural(missing, 'visitor')} could not be placed on the map.` : '', marks);
  }
  function renderPlaceList(list, more, rows, noun) {
    const button = element(more);
    const draw = all => {
      renderBreakdown(list, all ? rows : rows.slice(0, LISTED_PLACES), 'visitor');
      button.hidden = all || rows.length <= LISTED_PLACES;
      button.textContent = `Show all ${rows.length} ${noun}`;
    };
    button.onclick = () => draw(true);
    draw(false);
  }
  function renderVisitors(data) {
    if (data.since === null) {
      clearVisitors();
      element('visitors-status').textContent = 'No visits counted yet. The first one appears after someone opens the library.';
      return;
    }
    const today = data.daily[data.daily.length - 1].visitors;
    const places = visitorPlaces(data);
    element('figure-visitors').textContent = data.visitors.toLocaleString();
    element('figure-first').textContent = data.firstTime.toLocaleString();
    element('figure-today').textContent = today.toLocaleString();
    element('figure-countries').textContent = places.countryCount.toLocaleString();
    renderDaily(data.daily);
    renderMap(data);
    renderPlaceList('country-list', 'more-countries', places.countries, 'countries');
    renderPlaceList('city-list', 'more-cities', places.cities, 'cities');
    element('visitors-status').textContent = data.since > data.from ? `Counting began on ${dayLabel(data.since)}.` : '';
    element('visitor-glance').textContent = `${plural(today, 'visitor')} today`;
    element('visitor-glance').hidden = false;
    element('visitor-detail').hidden = false;
  }
  async function refreshVisitors() {
    const load = ++visitorLoad;
    for (const days of RANGES) element(`range-${days}`).setAttribute('aria-pressed', String(days === visitorRange));
    element('visitor-detail').setAttribute('aria-busy', 'true');
    if (element('visitor-detail').hidden) element('visitors-status').textContent = 'Loading visitors…';
    try {
      const data = await api(`/api/visitors?days=${visitorRange}`, undefined, true);
      if (load !== visitorLoad) return;
      if (!validVisitors(data)) throw new Error('Visitor counts unavailable.');
      renderVisitors(data);
      element('visitor-detail').removeAttribute('aria-busy');
    } catch (error) {
      if (load !== visitorLoad) return;
      clearVisitors();
      element('visitors-status').textContent = 'Visitor counts are unavailable. Use Refresh to try again.';
    }
  }
  async function refreshDashboard() {
    try { await refresh(); } catch (error) { status(errorMessage(error)); }
    if (csrfToken) await Promise.all([refreshVisitors(), refreshCatalogue()]);
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
  for (const days of RANGES) element(`range-${days}`).addEventListener('click', () => {
    if (!csrfToken || days === visitorRange) return;
    visitorRange = days;
    return refreshVisitors();
  });
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
