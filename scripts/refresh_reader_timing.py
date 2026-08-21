#!/usr/bin/env python3
"""Safely apply a reviewed timing artifact to an existing generated reader.

This is intentionally narrower than reader generation: it is for a repaired
onset artifact where source text, word maps, glosses, and English have not
changed. It validates the reader's exact sequence before rewriting only
`window.SONG_TIMINGS`, so no paid text stage is repeated merely to persist
timing evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def reader_sequence(path: Path) -> list[dict[str, Any]]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.SONG_SEQUENCE));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    value = json.loads(output)
    return value if isinstance(value, list) else []


def refresh(slug: str) -> None:
    song_dir = ROOT / "songs" / slug
    reader = song_dir / "data.js"
    timing_path = song_dir / ".transcription" / "pipeline" / "03-timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    fresh = timing.get("sequence", [])
    if timing.get("validation_errors"):
        raise RuntimeError("refusing timing artifact with validation errors")
    old = reader_sequence(reader)
    if len(old) != len(fresh):
        raise RuntimeError(f"sequence length differs: reader {len(old)}, timing {len(fresh)}")
    for index, (existing, replacement) in enumerate(zip(old, fresh)):
        for key in ("ref", "section", "repeats"):
            if existing.get(key) != replacement.get(key):
                raise RuntimeError(f"sequence mismatch at {index}: {key}")
    replacement = "window.SONG_TIMINGS = " + json.dumps([
        {"start": round(float(item["start"]), 3), "end": round(float(item["end"]), 3)} for item in fresh
    ], ensure_ascii=False, indent=2) + ";"
    original = reader.read_text(encoding="utf-8")
    updated, count = re.subn(r"window\.SONG_TIMINGS\s*=\s*\[.*?\];", replacement, original, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError("could not locate exactly one SONG_TIMINGS declaration")
    reader.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    args = parser.parse_args()
    refresh(args.slug)
