#!/usr/bin/env python3
"""Deterministically compress adjacent duplicate SONG_SEQUENCE entries."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slugs, or 'all'")
    parser.add_argument("--apply", action="store_true", help="Rewrite data.js in place.")
    return parser.parse_args()


def load_data(path: Path) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    output = subprocess.run(["node", "-e", script, str(path)], check=True, text=True, capture_output=True).stdout
    return json.loads(output)


def write_data(path: Path, data: dict[str, Any]) -> None:
    content = ("window.SONG_META = " + json.dumps(data["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_LINES = " + json.dumps(data["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_SEQUENCE = " + json.dumps(data["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_TIMINGS = " + json.dumps(data["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n")
    path.write_text(content, encoding="utf-8")


def normalize_song(slug: str, apply: bool) -> dict[str, Any]:
    path = ROOT / "songs" / slug / "data.js"
    if not path.is_file():
        return {"slug": slug, "changed": False, "merged_boundaries": 0, "before": 0, "after": 0, "status": "missing-data"}
    data = load_data(path)
    sequence = data.get("SONG_SEQUENCE", [])
    timings = data.get("SONG_TIMINGS", [])
    normalized_sequence, normalized_timings, merged = pipeline.compress_adjacent_reader_entries(sequence, timings)
    changed = merged > 0 or any("repeats" not in entry for entry in sequence)
    if apply and changed:
        data["SONG_SEQUENCE"] = normalized_sequence
        data["SONG_TIMINGS"] = normalized_timings
        write_data(path, data)
    return {
        "slug": slug,
        "status": "changed" if changed else "ready",
        "changed": changed,
        "merged_boundaries": merged,
        "before": len(sequence),
        "after": len(normalized_sequence),
    }


def main() -> int:
    options = parse_args()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
    reports = [normalize_song(slug, options.apply) for slug in slugs]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
