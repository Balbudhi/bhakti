#!/usr/bin/env python3
"""Report whether every published reader satisfies the canonical data contract.

This does not alter song data. It makes missing source script, meta, or timing
arrays visible before a migration or release rather than allowing a mixed
legacy/new format to look standardized by accident.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


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
    lines = data.get("SONG_LINES", {})
    if not isinstance(lines, dict):
        problems.append("SONG_LINES is not an object")
        lines = {}
    for line_id, line in lines.items():
        if not isinstance(line, dict):
            problems.append(f"{line_id} is not a line object")
            continue
        if not str(line.get("source", "")).strip():
            problems.append(f"{line_id} lacks source script")
        if not str(line.get("roman", "")).strip():
            problems.append(f"{line_id} lacks IAST")
        if not str(line.get("english", "")).strip():
            problems.append(f"{line_id} lacks literal English")
        if not isinstance(line.get("words"), list) or not line["words"]:
            problems.append(f"{line_id} lacks word glosses")
    sequence, timing = data.get("SONG_SEQUENCE", []), data.get("SONG_TIMINGS", [])
    if not isinstance(sequence, list) or not isinstance(timing, list) or len(sequence) != len(timing):
        problems.append("sequence/timing arrays are missing or differ in length")
    return {"slug": directory.name, "status": "ready" if not problems else "migration-needed", "problems": problems}


def main() -> int:
    reports = [audit_song(directory) for directory in sorted((ROOT / "songs").iterdir()) if directory.is_dir()]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report["status"] == "ready" for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
