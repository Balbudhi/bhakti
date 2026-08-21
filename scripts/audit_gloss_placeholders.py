#!/usr/bin/env python3
"""List public hover glosses that are placeholders rather than explanations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = {"proper name", "proper name or untranslated term", "untranslated term"}


def load(path: Path) -> dict[str, Any]:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.SONG_LINES));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def main() -> int:
    queue = []
    for song in sorted((ROOT / "songs").iterdir()):
        page = song / "data.js"
        if not page.is_file():
            continue
        for line_id, line in load(page).items():
            for word_index, word in enumerate(line.get("words", [])):
                if str(word.get("gloss") or "").strip().casefold() in PLACEHOLDERS:
                    queue.append({"slug": song.name, "line_id": line_id, "word_index": word_index,
                                  "roman": word.get("roman"), "source": line.get("source"),
                                  "english": line.get("english")})
    output = ROOT / ".transcription" / "gloss-placeholder-queue.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"count": len(queue), "items": queue}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"count": len(queue), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
