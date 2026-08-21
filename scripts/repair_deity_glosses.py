#!/usr/bin/env python3
"""Replace high-confidence deity/name placeholder glosses with identities.

Only exact, unambiguous forms are automated. Everything else remains in the
placeholder review queue for source/grammar-specific treatment.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLOSSES = {
    "rāma": "Viṣṇu's avatāra; husband of Sītā",
    "rām": "Viṣṇu's avatāra; husband of Sītā",
    "śāradā": "goddess of speech, learning, and inspired expression",
    "śiva": "the auspicious one; deity of transformation",
    "śiv": "the auspicious one; deity of transformation",
    "śaṅkara": "Śiva as the auspicious maker of good",
    "śaṅkar": "Śiva as the auspicious maker of good",
    "sītā": "Rāma's consort",
    "gaṇeśa": "elephant-headed remover of obstacles",
    "viṣṇu": "deity who preserves cosmic order",
    "lakṣmī": "goddess of flourishing and fortune",
    "rāvana": "king of Laṅkā and Rāma's adversary",
    "puṇḍalīka": "devotee associated with Viṭṭhala",
    "śirḍī": "town associated with Sāī Bābā",
    "īśvara": "the Lord; supreme ruler",
    "sarasvatī": "she who possesses flowing waters; Vedic goddess of speech, learning, and inspired expression",
    "sāībābā": "revered saint of Śirḍī",
}
PLACEHOLDERS = {"proper name", "proper name or untranslated term", "untranslated term"}


def canonical(value: str) -> str:
    value = value.casefold()
    return re.sub(r"[^a-zāīūṛṝḷṅñṭḍṇśṣḥ]", "", value)


def load(path: Path) -> dict:
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def write(path: Path, page: dict) -> None:
    path.write_text(
        "window.SONG_META = " + json.dumps(page["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_LINES = " + json.dumps(page["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_SEQUENCE = " + json.dumps(page["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
        "window.SONG_TIMINGS = " + json.dumps(page["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def main() -> int:
    changed = {}
    for song in sorted((ROOT / "songs").iterdir()):
        path = song / "data.js"
        if not path.is_file():
            continue
        page = load(path)
        count = 0
        for line in page.get("SONG_LINES", {}).values():
            for word in line.get("words", []):
                replacement = GLOSSES.get(canonical(str(word.get("roman") or "")))
                if replacement:
                    word["gloss"] = replacement
                    count += 1
        if count:
            write(path, page)
            changed[song.name] = count
    print(json.dumps({"songs": changed, "count": sum(changed.values())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
