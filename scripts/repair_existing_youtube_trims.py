#!/usr/bin/env python3
"""Apply a reviewed YouTube-edge trim to an already published song page.

New intake trims before timing. This migration is only for historical masters
whose trim model evidence was correct but whose older allowlist failed to apply
it. It shifts existing verified starts by exactly the removed leading duration
and refuses any lyric that begins inside the discarded material.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def load_song_page(path: Path) -> dict[str, Any]:
    import subprocess
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def replace_global(path: Path, name: str, value: Any) -> None:
    replacement = f"window.{name} = " + json.dumps(value, ensure_ascii=False, indent=2) + ";"
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(rf"window\.{name}\s*=\s*\[.*?\];", replacement, original, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"could not locate exactly one {name} declaration")
    path.write_text(updated, encoding="utf-8")


def repair(slug: str) -> dict[str, Any]:
    song_dir = ROOT / "songs" / slug
    page = song_dir / "data.js"
    page_data = load_song_page(page)
    timings = page_data.get("SONG_TIMINGS", [])
    sequence = page_data.get("SONG_SEQUENCE", [])
    source = pipeline.read_packet(song_dir / ".transcription" / "source.json") or {}
    options = argparse.Namespace(model=pipeline.MODEL, timeout=300, force=False)
    trim = pipeline.detect_youtube_trim(song_dir, source, options)
    if trim.get("validation_errors"):
        raise RuntimeError(f"trim validation failed: {trim['validation_errors']}")
    start = float(trim["trim_start"])
    if start <= 0.001:
        return {"slug": slug, "status": "no-leading-trim", "trim_start": start}
    if len(timings) != len(sequence):
        raise RuntimeError("public sequence/timing length mismatch")
    discard = 0
    while discard < len(timings):
        timing, entry = timings[discard], sequence[discard]
        spoken = str(entry.get("section") or "").casefold() == "spoken"
        if float(timing["end"]) <= start + 0.05 or (spoken and float(timing["start"]) < start):
            discard += 1
            continue
        break
    if discard == 0 and any(float(item["start"]) < start - 0.05 for item in timings):
        raise RuntimeError("a non-spoken lyric begins inside the proposed discarded intro")
    shifted = [{"start": round(float(item["start"]) - start, 3),
                "end": round(float(item["end"]) - start, 3)} for item in timings[discard:]]
    if any(item["start"] < 0 or item["end"] <= item["start"] for item in shifted):
        raise RuntimeError("trim offset would create invalid timings")
    pipeline.apply_lossless_trim(song_dir, trim)
    replace_global(page, "SONG_SEQUENCE", sequence[discard:])
    replace_global(page, "SONG_TIMINGS", shifted)
    timing_path = song_dir / ".transcription" / "pipeline" / "03-timing.json"
    packet = pipeline.read_packet(timing_path)
    if packet and isinstance(packet.get("sequence"), list):
        for item in packet["sequence"]:
            item["start"] = round(float(item["start"]) - start, 3)
            item["end"] = round(float(item["end"]) - start, 3)
        packet["duration_seconds"] = round(float(packet.get("duration_seconds", trim["duration"])) - start, 3)
        pipeline.write_json(timing_path, packet)
    return {"slug": slug, "status": "trimmed", "trim_start": start, "discarded_occurrences": discard,
            "new_duration": round(float(trim["trim_end"]) - start, 3)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="+")
    args = parser.parse_args()
    print(json.dumps([repair(slug) for slug in args.slugs], ensure_ascii=False, indent=2))
