#!/usr/bin/env python3
"""Fill missing source script from an existing private Gemini evidence packet.

This migration refuses fuzzy matches. It is for legacy readers whose private
transcript already has an exact source-script/IAST line pair; it never calls a
model, retranscribes audio, or invents source text.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_js(path: Path) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    return json.loads(subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout)


def key(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text).casefold()
    return "".join(char for char in decomposed if char.isalnum() and not unicodedata.combining(char))


def evidence_lines(song: Path) -> list[dict[str, Any]]:
    packet = json.loads((song / ".transcription" / "gemini-song-packet" / "01-transcription.json").read_text(encoding="utf-8"))
    lines = packet.get("packet", {}).get("lines", [])
    if not isinstance(lines, list):
        raise RuntimeError("evidence packet lacks transcript lines")
    return lines


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: migrate_source_from_evidence.py SONG-SLUG")
    song = ROOT / "songs" / sys.argv[1]
    data_path = song / "data.js"
    data = load_js(data_path)
    lines = data.get("SONG_LINES", {})
    if not isinstance(lines, dict):
        raise SystemExit("SONG_LINES missing")
    candidates: dict[str, list[dict[str, Any]]] = {}
    for candidate in evidence_lines(song):
        roman = str(candidate.get("roman", ""))
        source = str(candidate.get("source_text", ""))
        if roman and source:
            candidates.setdefault(key(roman), []).append(candidate)
    updates: dict[str, str] = {}
    for line_id, line in lines.items():
        if line.get("source"):
            continue
        matched = candidates.get(key(str(line.get("roman", ""))), [])
        unique = {str(item["source_text"]) for item in matched}
        if len(unique) != 1:
            raise SystemExit(f"blocked: {line_id} has {len(unique)} exact source-script matches")
        updates[line_id] = unique.pop()
    if not updates:
        print("nothing to migrate")
        return 0
    language = (data.get("SONG_META", {}).get("languages") or [""])[0]
    for line_id, source in updates.items():
        lines[line_id]["source"] = source
        lines[line_id]["sourceLanguage"] = {"Hindi": "hi", "Kannada": "kn", "Punjabi": "pa", "Sanskrit": "sa"}.get(language, "")
    content = ("window.SONG_META = " + json.dumps(data.get("SONG_META", {}), ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_LINES = " + json.dumps(lines, ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_SEQUENCE = " + json.dumps(data.get("SONG_SEQUENCE", []), ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_TIMINGS = " + json.dumps(data.get("SONG_TIMINGS", []), ensure_ascii=False, indent=2) + ";\n")
    data_path.write_text(content, encoding="utf-8")
    print(json.dumps({"song": song.name, "updated": sorted(updates)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
