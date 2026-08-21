#!/usr/bin/env python3
"""Zero-cost corpus audit for public Bhakti transcription integrity.

This does not pretend to prove every heard syllable. It checks every public
reader against its private audited transcript and emits a narrow witness/audio
review queue instead of silently normalizing a possible performance variant.
"""

from __future__ import annotations

import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def signature(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(ch for ch in value if ch.isalnum() and not unicodedata.combining(ch))


def load_reader(path: Path) -> dict[str, Any]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def audit_song(song: Path) -> dict[str, Any]:
    reader = load_reader(song / "data.js")
    lines = reader.get("SONG_LINES", {})
    sequence = reader.get("SONG_SEQUENCE", [])
    timings = reader.get("SONG_TIMINGS", [])
    findings: list[str] = []
    if len(sequence) != len(timings):
        findings.append("public sequence/timing length mismatch")
    previous = -1.0
    for index, timing in enumerate(timings):
        start = timing.get("start") if isinstance(timing, dict) else None
        if not isinstance(start, (int, float)) or start <= previous:
            findings.append(f"public timing {index} is missing or non-increasing")
        if isinstance(start, (int, float)):
            previous = start
    for ref, line in lines.items():
        if not str(line.get("source") or "").strip():
            findings.append(f"{ref} lacks source script")
        if not str(line.get("roman") or "").strip():
            findings.append(f"{ref} lacks romanization")
        if not isinstance(line.get("words"), list) or not line["words"]:
            findings.append(f"{ref} lacks word map")
    audit_path = song / ".transcription" / "pipeline" / "02-transcript-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else None
    if audit:
        packet = audit.get("packet", {})
        if packet.get("uncertainties"):
            findings.append("private audited transcript retains uncertainty")
        audited = {item.get("id"): item for item in packet.get("verified_lines", [])}
        for ref, line in lines.items():
            if ref not in audited:
                findings.append(f"{ref} absent from private audited transcript")
                continue
            item = audited[ref]
            if signature(str(line.get("source") or "")) != signature(str(item.get("source_text") or "")):
                findings.append(f"{ref} public source differs from audited source")
            if signature(str(line.get("roman") or "")) != signature(str(item.get("roman") or "")):
                findings.append(f"{ref} public roman differs from audited roman")
    return {"slug": song.name, "audited": bool(audit), "finding_count": len(findings), "findings": findings}


def main() -> int:
    reports = [audit_song(song) for song in sorted((ROOT / "songs").glob("*")) if (song / "data.js").is_file()]
    payload = {"reader_count": len(reports), "clean_count": sum(not row["findings"] for row in reports),
               "review_queue": [row for row in reports if row["findings"]]}
    output = ROOT / ".transcription" / "corpus-transcript-audit.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
