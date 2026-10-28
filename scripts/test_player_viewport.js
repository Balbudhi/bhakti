// Exercise the real app bootstrap with independent viewport/lifecycle events.
// This is a viewport-input regression, not an emulation of WebKit compositing.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function boot({ visual = true } = {}) {
  const styles = new Map();
  const frames = [];
  const window = new EventTarget();
  window.innerHeight = 844;
  const document = new EventTarget();
  document.visibilityState = 'visible';
  document.documentElement = {
    clientHeight: 844,
    classList: { toggle() {} },
    style: { setProperty: (name, value) => styles.set(name, value) },
  };
  const viewport = visual ? Object.assign(new EventTarget(), {
    height: 844, offsetTop: 0, scale: 1,
  }) : null;
  window.visualViewport = viewport;
  const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
  const end = source.indexOf('  const Queue = window.BHAKTI_QUEUE;');
  assert.ok(end > 0, 'app bootstrap boundary exists');
  vm.runInNewContext(source.slice(0, end) + '\n})();', {
    window, document, navigator: {}, matchMedia: () => ({ matches: false }),
    requestAnimationFrame: callback => { frames.push(callback); return frames.length; },
  });
  return { window, document, viewport, styles, frames,
    flush() { frames.splice(0).forEach(callback => callback()); },
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
