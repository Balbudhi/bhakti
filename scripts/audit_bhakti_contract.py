#!/usr/bin/env python3
"""Report whether every published reader satisfies the canonical data contract.

This does not alter song data. It makes missing source script, meta, or timing
arrays visible before a migration or release rather than allowing a mixed
legacy/new format to look standardized by accident.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALID_SECTIONS = {"invocation", "refrain", "verse", "bridge", "closing", "spoken", "instrumental"}
REQUIRED_META = {"title", "credit", "languages", "subjectTags", "translationStatus", "sourceStatus"}


def load_data(path: Path) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    output = subprocess.run(["node", "-e", script, str(path)], check=True, text=True, capture_output=True).stdout
    return json.loads(output)


def audit_song(directory: Path) -> dict[str, Any]:
    data_path = directory / "data.js"
    problems: list[str] = []
    if not data_path.is_file():
        return {"slug": directory.name, "status": "legacy", "problems": ["no song-local data.js"]}
    try:
        data = load_data(data_path)
    except subprocess.CalledProcessError as exc:
        return {"slug": directory.name, "status": "blocked", "problems": [f"data.js cannot execute: {exc.stderr.strip()}"]}
    required = ["SONG_META", "SONG_LINES", "SONG_SEQUENCE", "SONG_TIMINGS"]
    problems.extend(f"missing window.{key}" for key in required if key not in data)
    meta = data.get("SONG_META", {})
    if not isinstance(meta, dict):
        problems.append("SONG_META is not an object")
    else:
        problems.extend(f"SONG_META lacks {key}" for key in sorted(REQUIRED_META - set(meta)))
        if not isinstance(meta.get("languages"), list) or not meta.get("languages"):
            problems.append("SONG_META languages must be a non-empty list")
        if not isinstance(meta.get("subjectTags"), list):
            problems.append("SONG_META subjectTags must be a list")
    lines = data.get("SONG_LINES", {})
    if not isinstance(lines, dict):
        problems.append("SONG_LINES is not an object")
        lines = {}
    sequence, timing = data.get("SONG_SEQUENCE", []), data.get("SONG_TIMINGS", [])
    instrumental_refs = {entry.get("ref") for entry in sequence if isinstance(entry, dict) and entry.get("section") == "instrumental"}
    for line_id, line in lines.items():
        if not isinstance(line, dict):
            problems.append(f"{line_id} is not a line object")
            continue
        if line_id not in instrumental_refs and not str(line.get("source", "")).strip():
            problems.append(f"{line_id} lacks source script")
        if not str(line.get("roman", "")).strip():
            problems.append(f"{line_id} lacks IAST")
        if not str(line.get("english", "")).strip():
            problems.append(f"{line_id} lacks literal English")
        if not isinstance(line.get("words"), list) or not line["words"]:
            problems.append(f"{line_id} lacks word glosses")
        else:
            roman = str(line.get("roman", ""))
            cursor = 0
            for word_index, word in enumerate(line["words"]):
                token = str(word.get("roman", "")) if isinstance(word, dict) else ""
                gloss = str(word.get("gloss", "")) if isinstance(word, dict) else ""
                at = roman.casefold().find(token.casefold(), cursor) if token else -1
                if at < 0 or not gloss.strip():
                    problems.append(f"{line_id} word[{word_index}] cannot map to roman text or lacks a gloss")
                    break
                cursor = at + len(token)
            for marker in re.finditer(r"\{([^:}]+):([^}]*)\}", str(line.get("english", ""))):
                try:
                    indices = [int(value.strip()) for value in marker.group(1).split(",")]
                except ValueError:
                    problems.append(f"{line_id} has malformed English word linkage")
                    break
                if any(index < 0 or index >= len(line["words"]) for index in indices):
                    problems.append(f"{line_id} English linkage references an invalid word index")
                    break
    if not isinstance(sequence, list) or not isinstance(timing, list) or len(sequence) != len(timing):
        problems.append("sequence/timing arrays are missing or differ in length")
    if isinstance(sequence, list):
        previous_start = -0.001
        for index, entry in enumerate(sequence):
            if not isinstance(entry, dict) or entry.get("section") not in VALID_SECTIONS:
                problems.append(f"sequence[{index}] lacks a canonical section")
                continue
            if entry.get("ref") not in lines:
                problems.append(f"sequence[{index}] references unknown line {entry.get('ref')!r}")
            if index < len(timing):
                point = timing[index]
                try:
                    start, end = float(point["start"]), float(point["end"])
                    if start < 0 or end < start or start + 0.01 < previous_start:
                        raise ValueError
                    previous_start = start
                except (KeyError, TypeError, ValueError):
                    problems.append(f"timing[{index}] is invalid or out of order")
    return {"slug": directory.name, "status": "ready" if not problems else "migration-needed", "problems": problems}


def main() -> int:
    reports = [audit_song(directory) for directory in sorted((ROOT / "songs").iterdir()) if directory.is_dir()]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report["status"] == "ready" for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
