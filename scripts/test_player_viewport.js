// Exercise the real app bootstrap with independent viewport/lifecycle events.
// This is a viewport-input regression, not an emulation of WebKit compositing.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function boot({ visual = true, installed = false, screen = null, activeElement = null } = {}) {
  const styles = new Map();
  const frames = new Map();
  const timers = new Map();
  const writes = [];
  let frameId = 0, timerId = 0, now = 0;
  const window = new EventTarget();
  window.innerHeight = 844;
  if (screen) window.screen = screen;
  const document = new EventTarget();
  document.visibilityState = 'visible';
  document.activeElement = activeElement;
  document.documentElement = {
    clientHeight: 844,
    classList: { toggle() {} },
    style: { setProperty: (name, value) => { styles.set(name, value); writes.push([name, value]); } },
  };
  const viewport = visual ? Object.assign(new EventTarget(), {
    height: 844, offsetTop: 0, scale: 1,
  }) : null;
  window.visualViewport = viewport;
  const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
  const end = source.indexOf('  const Queue = window.BHAKTI_QUEUE;');
  assert.ok(end > 0, 'app bootstrap boundary exists');
  vm.runInNewContext(source.slice(0, end) + '\n})();', {
    window, document, navigator: {}, matchMedia: q => ({ matches: installed && q.includes('standalone') }),
    requestAnimationFrame: callback => { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: (callback, delay) => { timers.set(++timerId, { callback, at: now + delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  return { window, document, viewport, styles, timers, writes,
    get frames() { return [...frames.values()]; },
    flush() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); },
    dropFrames() { frames.clear(); },
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= now) { timers.delete(id); timer.callback(); }
      }
    },
    fire(target, name) { target.dispatchEvent(new Event(name)); },
  };
}

test('initial anchor uses measured visible bounds rather than CSS viewport units', () => {
  const app = boot();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
  assert.equal(app.styles.get('--app-viewport-top'), '0px');
});

test('visual viewport rotation settles even while layout height is stale', () => {
  const app = boot();
  app.viewport.height = 390;
  app.fire(app.viewport, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '390px');
  app.viewport.height = 844;
  app.fire(app.viewport, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
});

test('viewport pan and keyboard bounds use measured offset, never document scroll', () => {
  const app = boot();
  app.window.scrollY = 1200;
  app.viewport.height = 500;
  app.viewport.offsetTop = 120;
  app.fire(app.viewport, 'resize');
  app.fire(app.viewport, 'scroll');
  assert.equal(app.frames.length, 1, 'coalesce one viewport update per frame');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '500px');
  assert.equal(app.styles.get('--app-viewport-top'), '120px');
});

test('restored pages and foreground return refresh bounds without a resize event', () => {
  const app = boot();
  app.viewport.height = 600;
  app.fire(app.window, 'pageshow');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '600px');
  app.viewport.height = 844;
  app.fire(app.document, 'visibilitychange');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
});

test('fallback without VisualViewport uses current layout height', () => {
  const app = boot({ visual: false });
  app.window.innerHeight = 390;
  app.fire(app.window, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '390px');
});

test('pinch zoom keeps the player on the visible bottom without counter-scaling', () => {
  const zoom = boot();
  zoom.viewport.scale = 2;
  zoom.viewport.height = 422;
  zoom.viewport.offsetTop = 180;
  zoom.fire(zoom.viewport, 'resize');
  zoom.flush();
  assert.equal(zoom.styles.get('--app-viewport-height'), '422px');
  assert.equal(zoom.styles.get('--app-viewport-top'), '180px');
  // The visible lower edge is 180 + 422 = 602 CSS pixels. Docking at the
  // 844px layout edge leaves the controls below the magnified visible region.
  assert.equal(parseFloat(zoom.styles.get('--app-viewport-top'))
    + parseFloat(zoom.styles.get('--app-viewport-height')), 602);
});

test('zoom pan and zoom return retain measured bounds across the old scale cutoff', () => {
  const app = boot();
  for (const [scale, height, top] of [[2, 422, 180], [2, 422, 260], [1.02, 827, 10], [1, 844, 0]]) {
    Object.assign(app.viewport, { scale, height, offsetTop: top });
    app.fire(app.viewport, 'resize');
    app.fire(app.viewport, 'scroll');
    app.flush();
    assert.equal(app.styles.get('--app-viewport-height'), `${height}px`, `height at scale ${scale}`);
    assert.equal(app.styles.get('--app-viewport-top'), `${top}px`, `pan at scale ${scale}`);
  }
});

test('transient invalid viewport dimensions cannot collapse the player anchor', () => {
  const app = boot();
  app.viewport.height = 0;
  app.fire(app.viewport, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
  app.viewport.height = 700;
  app.viewport.offsetTop = NaN;
  app.fire(app.viewport, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-top'), '0px');
});

test('unavailable layout and visual measurements retain the last usable bounds', () => {
  const app = boot();
  app.viewport.height = 600;
  app.viewport.offsetTop = 80;
  app.fire(app.viewport, 'resize');
  app.flush();
  app.viewport.height = NaN;
  app.window.innerHeight = 0;
  app.document.documentElement.clientHeight = 0;
  app.fire(app.window, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '600px');
  assert.equal(app.styles.get('--app-viewport-top'), '80px');
  app.document.documentElement.clientHeight = 720;
  app.fire(app.window, 'resize');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '720px');
  assert.equal(app.styles.get('--app-viewport-top'), '0px');
});

// Lifecycle events may arrive before a positive but stale native measurement
// settles. Sample a finite window, cancel stale work when hidden/restarted, and
// let ordinary scrolling repair silently changed measurements. No geometry is
// inferred, no scrolling is forced, and there is no continuous polling.
for (const event of ['pageshow', 'orientationchange', 'visibilitychange', 'focusout']) {
  test(`${event} samples delayed viewport settlement without another resize event`, () => {
    const app = boot();
    app.viewport.height = 390;
    app.fire(['visibilitychange', 'focusout'].includes(event) ? app.document : app.window, event);
    app.flush();
    assert.equal(app.styles.get('--app-viewport-height'), '390px');
    for (const [delay, height] of [[100, 600], [200, 700], [700, 844]]) {
      app.viewport.height = height;
      app.advance(delay);
      app.flush();
      assert.equal(app.styles.get('--app-viewport-height'), `${height}px`);
    }
    assert.equal(app.timers.size, 0, 'settling work ends after its finite window');
    app.advance(10000);
    assert.equal(app.frames.length, 0, 'there is no ongoing poll');
  });
}

test('foreground recovery replaces a dropped pre-background animation frame', () => {
  const app = boot();
  app.viewport.height = 390;
  app.fire(app.viewport, 'resize');
  app.dropFrames(); // The browser suspends/discards an outstanding callback.
  app.document.visibilityState = 'hidden';
  app.fire(app.document, 'visibilitychange');
  app.document.visibilityState = 'visible';
  app.viewport.height = 700;
  app.fire(app.document, 'visibilitychange');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '700px');
});

test('hiding cancels settling and rejects hidden viewport writes', () => {
  const app = boot();
  app.fire(app.window, 'pageshow');
  assert.equal(app.timers.size, 3);
  app.document.visibilityState = 'hidden';
  app.fire(app.document, 'visibilitychange');
  assert.equal(app.frames.length, 0);
  assert.equal(app.timers.size, 0);
  app.viewport.height = 390;
  app.fire(app.viewport, 'resize');
  app.fire(app.window, 'pageshow');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
  assert.equal(app.timers.size, 0);
});

test('new lifecycle events replace pending settling checks', () => {
  const app = boot();
  app.fire(app.window, 'pageshow');
  const oldTimers = [...app.timers.keys()];
  app.fire(app.window, 'orientationchange');
  assert.equal(app.timers.size, 3);
  assert.ok(oldTimers.every(id => !app.timers.has(id)));
  assert.equal(app.frames.length, 1);
});

test('ordinary scroll and scroll completion refresh silently changed bounds', () => {
  const app = boot();
  app.window.scrollY = 1200;
  app.viewport.height = 700;
  app.fire(app.window, 'scroll');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '700px');
  app.viewport.height = 844;
  app.fire(app.window, 'scrollend');
  app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
  assert.equal(app.styles.get('--app-viewport-top'), '0px');
});

test('unchanged viewport events do not rewrite layout properties', () => {
  const app = boot();
  const initialWrites = app.writes.length;
  for (let index = 0; index < 4; index++) {
    app.fire(app.viewport, 'scroll');
    app.fire(app.window, 'scroll');
    app.flush();
  }
  assert.equal(app.writes.length, initialWrites);
  app.viewport.offsetTop = 120;
  app.fire(app.viewport, 'scroll');
  app.flush();
  assert.equal(app.writes.length, initialWrites + 1);
  assert.deepEqual(app.writes.at(-1), ['--app-viewport-top', '120px']);
});


test('installed app: a stale short viewport after resume is corrected to the screen height', () => {
  const app = boot({ installed: true, screen: { width: 390, height: 844 } });
  app.viewport.height = 512;                       // iOS reports a stale height; nothing corrects it later
  app.fire(app.window, 'pageshow');
  app.flush(); app.advance(1000); app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '844px');
});

test('installed app: a real keyboard (text field focused) is not overridden', () => {
  const app = boot({ installed: true, screen: { width: 390, height: 844 }, activeElement: { tagName: 'INPUT', type: 'search' } });
  app.viewport.height = 512;
  app.fire(app.viewport, 'resize'); app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '512px');
});

test('installed app: pinch zoom keeps the measured visible bounds', () => {
  const app = boot({ installed: true, screen: { width: 390, height: 844 } });
  app.viewport.height = 422; app.viewport.scale = 2;
  app.fire(app.viewport, 'resize'); app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '422px');
});

test('browser tab: measured bounds are trusted (toolbars are real)', () => {
  const app = boot({ installed: false, screen: { width: 390, height: 844 } });
  app.viewport.height = 700;
  app.fire(app.viewport, 'resize'); app.flush();
  assert.equal(app.styles.get('--app-viewport-height'), '700px');
});
