#!/usr/bin/env python3
"""Apply reviewed translation-style fixes to existing Bhakti readers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slug(s), or 'all'.")
    parser.add_argument("--apply", action="store_true", help="Rewrite data.js in place.")
    return parser.parse_args()


def load_reader(slug: str) -> dict[str, Any]:
    path = ROOT / "songs" / slug / "data.js"
    if not path.is_file():
        raise RuntimeError(f"missing data.js for {slug}")
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    return json.loads(subprocess.run(
        ["node", "-e", script, str(path)], check=True, text=True, capture_output=True
    ).stdout)


def write_reader(slug: str, data: dict[str, Any]) -> None:
    path = ROOT / "songs" / slug / "data.js"
    content = ("window.SONG_META = " + json.dumps(data["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_LINES = " + json.dumps(data["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_SEQUENCE = " + json.dumps(data["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_TIMINGS = " + json.dumps(data["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n")
    path.write_text(content, encoding="utf-8")


def plain_english(value: str) -> str:
    return re.sub(r"\{[^:{}]*:([^{}]*)\}", r"\1", value)


def review_path(slug: str) -> Path:
    return ROOT / "songs" / slug / ".transcription" / "translation-style-audit" / "review.json"


def load_review(slug: str) -> dict[str, Any]:
    path = review_path(slug)
    if not path.is_file():
        raise RuntimeError(f"missing translation-style review for {slug}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("reviews"), list):
        raise RuntimeError(f"invalid translation-style review for {slug}")
    return value


def validate_review(slug: str, reader: dict[str, Any], review: dict[str, Any]) -> list[str]:
    lines = reader.get("SONG_LINES", {})
    reviews = review.get("reviews", [])
    registry = pipeline.preserved_term_registry().get("terms", {})
    expected = list(lines.keys())
    observed = [row.get("id") for row in reviews]
    errors: list[str] = []
    if observed != expected:
        errors.append(f"{slug} review IDs differ: expected {expected[:5]}..., got {observed[:5]}...")
    for row in reviews:
        line = lines.get(row.get("id"))
        if not isinstance(line, dict):
            continue
        words = line.get("words", [])
        for segment in row.get("segments", []):
            for index in segment.get("word_indices", []):
                if not isinstance(index, int) or not 0 <= index < len(words):
                    errors.append(f"{slug}:{row.get('id')} has invalid word index {index!r}")
        revised = str(row.get("revised_english", "")).strip()
        if not revised:
            errors.append(f"{slug}:{row.get('id')} lacks revised_english")
            continue
        rendered = plain_english(pipeline.segment_english(row.get("segments", []), "")).strip()
        if re.sub(r"\s+", " ", rendered) != re.sub(r"\s+", " ", revised):
            errors.append(f"{slug}:{row.get('id')} segments do not reconstruct revised_english")
        uncertainty = str(row.get("uncertainty", "")).strip().casefold()
        if row.get("change_needed") and uncertainty not in {"", "none"}:
            errors.append(f"{slug}:{row.get('id')} is marked changed but still uncertain")
        for word in words:
            if not isinstance(word, dict) or not word.get("preserve_in_english"):
                continue
            concept_key = str(word.get("concept_key", "")).strip()
            canonical = str(registry.get(concept_key, {}).get("iast", "")).strip()
            if canonical and canonical.casefold() not in revised.casefold():
                errors.append(f"{slug}:{row.get('id')} would drop preserved term {canonical}")
    return errors


def apply_review(reader: dict[str, Any], review: dict[str, Any]) -> tuple[dict[str, Any], int]:
    changed = 0
    reviews = {row["id"]: row for row in review["reviews"]}
    lines = reader["SONG_LINES"]
    for line_id, line in lines.items():
        row = reviews[line_id]
        if not row.get("change_needed"):
            continue
        new_english = pipeline.segment_english(row.get("segments", []), str(row.get("revised_english", "")))
        if new_english != line.get("english"):
            line["english"] = new_english
            changed += 1
    return reader, changed


def run_slug(slug: str, apply: bool) -> dict[str, Any]:
    reader = load_reader(slug)
    review = load_review(slug)
    errors = validate_review(slug, reader, review)
    if errors:
        raise RuntimeError("; ".join(errors[:5]))
    updated, changed = apply_review(reader, review)
    if apply and changed:
        write_reader(slug, updated)
    return {"slug": slug, "changed_lines": changed, "status": "ready" if not changed else ("applied" if apply else "reviewed")}


def main() -> int:
    options = parse_args()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
    results = []
    for slug in slugs:
        try:
            results.append(run_slug(slug, options.apply))
        except Exception as exc:
            results.append({"slug": slug, "status": "blocked", "error": str(exc)})
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(result["status"] == "blocked" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
