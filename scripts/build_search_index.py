#!/usr/bin/env python3
"""Generate deferred public lyric search from this release's performed reader text.

No private review fields, unused definitions or instrumental rows enter the index.
Normalization uses the actual public search implementation, once at build time.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build_search_index(root: Path, output: Path | None = None) -> dict:
    root = Path(root)
    script = r'''
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = process.argv[1];
const runtime = {window: {}, document: {}};
vm.runInNewContext(fs.readFileSync(path.join(root, 'assets/library.js'), 'utf8'), runtime);
const forms = runtime.window.BHAKTI_SEARCH.searchForms;
const songs = {};
for (const slug of fs.readdirSync(path.join(root, 'songs')).sort()) {
  const file = path.join(root, 'songs', slug, 'data.js');
  if (!fs.existsSync(file)) continue;
  const reader = {window: {}};
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), reader, {filename: file, timeout: 1000});
  const {SONG_LINES: lines, SONG_SEQUENCE: sequence} = reader.window;
  if (!lines || typeof lines !== 'object' || !Array.isArray(sequence)) {
    throw Error(`Invalid lyric search reader: ${slug}`);
  }
  const values = new Set(), seen = new Set();
  for (const occurrence of sequence) {
    if (occurrence.section === 'instrumental' || seen.has(occurrence.ref)) continue;
    const line = lines[occurrence.ref];
    if (!line) throw Error(`Missing performed line: ${slug}/${occurrence.ref}`);
    seen.add(occurrence.ref);
    // Keep field/line boundaries: phrases may not be invented across them.
    const english = String(line.english || '').replace(/\{[\d,\s]+:([^{}]*)\}/g, '$1');
    for (const value of [line.source, line.roman, english, ...(line.words || []).map(word => word.gloss)]) {
      if (typeof value === 'string') for (const form of forms(value)) values.add(form);
    }
  }
  songs[slug] = [...values];
}
process.stdout.write(JSON.stringify({schemaVersion: 1, songs}));
'''
    result = subprocess.run(['node', '-e', script, str(root.resolve())],
                            capture_output=True, text=True, check=True)
    index = json.loads(result.stdout)
    destination = Path(output) if output is not None else root / 'data/search-index.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    build_search_index(args.root, args.output)


if __name__ == '__main__':
    main()
