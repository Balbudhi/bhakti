#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require.resolve("../assets/pwa.js"), "utf8");
const original = "width=device-width, initial-scale=1, viewport-fit=cover";
function viewportFor({ ios = false, standaloneTouch = false } = {}) {
  const viewport = { content: original, getAttribute() { return this.content; }, setAttribute(_, value) { this.content = value; } };
  const document = { querySelector: selector => selector === 'meta[name="viewport"]' ? viewport : null };
  const window = { matchMedia: () => ({ matches: standaloneTouch }) };
  // Viewport policy must apply even without service-worker support.
  vm.runInNewContext(source, { document, window, navigator: { standalone: ios } });
  return viewport.content;
}
assert.equal(viewportFor(), original, "Ordinary browser/desktop viewport stays scalable");
for (const mode of [{ ios: true }, { standaloneTouch: true }]) {
  const content = viewportFor(mode);
  assert.match(content, /maximum-scale=1/);
  assert.match(content, /user-scalable=no/);
  assert.match(content, /viewport-fit=cover/, "Retain safe-area configuration");
  assert.match(content, /width=device-width/);
}
console.log("PASS: mobile standalone fixed scale; browser viewport and safe-area settings preserved");
