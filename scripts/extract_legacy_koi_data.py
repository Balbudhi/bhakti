#!/usr/bin/env python3
"""Move Koi Hor's embedded legacy data into its song-local data.js file.

This is a mechanical extraction only: it preserves existing romanization,
English, glosses, sequence, and timings without claiming missing source script.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "assets" / "song.js"
SONG = ROOT / "songs" / "koi-hor-nahi"


def between(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


def main() -> int:
    asset = ASSET.read_text(encoding="utf-8")
    lines = between(asset, "const LINES =", "/* SEQUENCE").replace("const LINES =", "window.SONG_LINES =", 1)
    sequence = between(asset, "const SEQUENCE =", "/* =============================================================\n   RENDER").replace("const SEQUENCE =", "window.SONG_SEQUENCE =", 1)
    timings = (SONG / "timings.js").read_text(encoding="utf-8")
    start = timings.index("window.SONG_TIMINGS =")
    timings = timings[start:]
    meta = '''window.SONG_META = {
  title: "Koī Hor Nahī Hai Merā",
  singer: "Aman Ji",
  album: "Shri Mata Vaishno Devi Bhawan",
  devotionalFocus: "Śakti",
  languages: ["Punjabi"],
  subjectTags: ["Śakti"],
  translationStatus: "legacy-review-required",
  sourceStatus: "source-script-migration-required"
};

'''
    (SONG / "data.js").write_text(meta + lines + "\n" + sequence + "\n" + timings, encoding="utf-8")
    print(SONG / "data.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
