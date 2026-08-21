#!/usr/bin/env python3
"""Rebuild every public song shell and normalize deterministic reader data."""

from __future__ import annotations

import json
from pathlib import Path

import audit_bhakti_contract as audit
import bhakti_pipeline as pipeline
import gloss_policy
import source_word_map


ROOT = Path(__file__).resolve().parents[1]


def data_javascript(data: dict) -> str:
    blocks = []
    for name in ("SONG_META", "SONG_LINES", "SONG_SEQUENCE", "SONG_TIMINGS"):
        blocks.append(f"window.{name} = {json.dumps(data[name], ensure_ascii=False, indent=2)};")
    return "\n\n".join(blocks) + "\n"


def rebuild(directory: Path) -> tuple[bool, bool]:
    data_path = directory / "data.js"
    if not data_path.is_file():
        return False, False
    data = audit.load_data(data_path)
    changed = False
    for line in data["SONG_LINES"].values():
        words = line.get("words", [])
        cleaned = [gloss_policy.clean_word(word) for word in words]
        if cleaned != words:
            line["words"] = cleaned
            words = cleaned
            changed = True
        source_words = source_word_map.build_source_words(str(line.get("source") or ""), words)
        if source_words != line.get("sourceWords"):
            line["sourceWords"] = source_words
            changed = True
    if changed:
        data_path.write_text(data_javascript(data), encoding="utf-8")
    page = pipeline.page_html(data["SONG_META"])
    index_path = directory / "index.html"
    page_changed = not index_path.is_file() or index_path.read_text(encoding="utf-8") != page
    if page_changed:
        index_path.write_text(page, encoding="utf-8")
    return changed, page_changed


def main() -> int:
    data_changes, page_changes = [], []
    for directory in sorted((ROOT / "songs").iterdir()):
        if not directory.is_dir():
            continue
        data_changed, page_changed = rebuild(directory)
        if data_changed:
            data_changes.append(directory.name)
        if page_changed:
            page_changes.append(directory.name)
    pipeline.write_catalogue()
    print(json.dumps({"normalizedReaders": data_changes, "rebuiltPages": page_changes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
