#!/usr/bin/env python3
"""Create an evidence-state inventory for every public Bhakti song page."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def catalogue() -> list[dict]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.BHAKTI_SONGS));"
    output = subprocess.run(["node", "-e", script, str(ROOT / "data" / "songs.js")], check=True,
                            capture_output=True, text=True).stdout
    return json.loads(output)


def main() -> int:
    witness_registry = json.loads((ROOT / "data" / "source_witnesses.json").read_text(encoding="utf-8"))
    discovery_path = ROOT / ".transcription" / "metadata-discovery-queue.json"
    discovery = json.loads(discovery_path.read_text(encoding="utf-8")) if discovery_path.is_file() else {"items": []}
    candidates = {item["slug"]: item for item in discovery.get("items", [])}
    rows = []
    for song in catalogue():
        slug = song["slug"]
        packet = ROOT / "songs" / slug / ".transcription" / "pipeline" / "02-transcript-audit.json"
        if slug in witness_registry.get("works", {}):
            state = "witness-registered"
        elif candidates.get(slug, {}).get("candidates"):
            state = "candidate-found"
        elif packet.is_file():
            state = "audio-audited"
        else:
            state = "needs-audit"
        rows.append({"slug": slug, "title": song.get("title"), "writer": song.get("writer"),
                     "singer": song.get("singer"), "state": state})
    counts = {state: sum(row["state"] == state for row in rows) for state in sorted({row["state"] for row in rows})}
    output = ROOT / ".transcription" / "witness-inventory.json"
    output.write_text(json.dumps({"counts": counts, "songs": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
