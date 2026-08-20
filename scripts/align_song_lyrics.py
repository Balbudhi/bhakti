#!/usr/bin/env python3
"""Run one lyric-aware Gemini timing pass for an existing song reader."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import process_song_gemini as gemini


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=300)
    return parser.parse_args()


def line_catalog(data: Path) -> dict[str, str]:
    source = data.read_text(encoding="utf-8")
    rows = re.findall(r'^\s{2}([A-Za-z0-9_]+):\s*\{[\s\S]*?^\s{4}roman:\s*"([^"]+)"', source, flags=re.MULTILINE)
    if not rows:
        raise RuntimeError("could not parse SONG_LINES")
    return dict(rows)


def validate(sequence: list[dict[str, Any]], catalogue: dict[str, str], duration: float) -> list[str]:
    errors: list[str] = []
    last = -0.001
    for index, entry in enumerate(sequence):
        ref = entry.get("ref")
        if ref not in catalogue:
            errors.append(f"entry {index} uses unknown ref {ref!r}")
        try:
            start, end = float(entry["start"]), float(entry["end"])
        except (TypeError, ValueError, KeyError):
            errors.append(f"entry {index} has nonnumeric timing")
            continue
        if not 0 <= start <= end <= duration:
            errors.append(f"entry {index} falls outside 0–{duration:.3f}s")
        if start + 0.01 < last:
            errors.append(f"entry {index} is out of performance order")
        last = start
    return errors


def main() -> int:
    options = parse_args()
    song = options.song_dir.resolve()
    audio, data = song / "audio.m4a", song / "data.js"
    if not audio.is_file() or not data.is_file():
        raise SystemExit("song directory needs audio.m4a and data.js")
    catalogue = line_catalog(data)
    duration = gemini.duration_seconds(audio)
    prompt = f"""You are doing the only timing/alignment pass for an existing devotional song reader. Listen to the ENTIRE attached recording, whose duration is exactly {duration:.3f} seconds. The canonical display lyrics below are already reviewed; do not rewrite their words or invent new substitutes.

Map every audible lyric instance to one canonical `ref`. Include every returning line, pickup, invocation, response, and vocal tag in actual order. A new entry is required whenever a line returns after another line. `repeats` is allowed only for immediately contiguous identical occurrences. `start` is the first audible syllable of that displayed entry; `end` is the end of its final contiguous occurrence. Do not put a time outside 0–{duration:.3f}. If an audible line cannot map exactly, put it in `unmatched` rather than forcing it into the catalogue.

Canonical lyric catalogue:
{json.dumps(catalogue, ensure_ascii=False)}

Return strict JSON: {{"sequence":[{{"ref":"catalogue-id","repeats":1,"start":0.0,"end":0.0,"reason":""}}],"unmatched":[{{"start":0.0,"end":0.0,"heard":"","reason":""}}],"notes":[]}}."""
    result = gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=options.timeout)
    packet = result["packet"]
    sequence = packet.get("sequence", [])
    errors = validate(sequence if isinstance(sequence, list) else [], catalogue, duration)
    if packet.get("unmatched"):
        errors.append("one or more audible lines did not map to the reviewed catalogue")
    output = song / ".transcription" / "lyric-alignment.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"model_requested": options.model, "duration_seconds": duration, "result": result, "validation_errors": errors, "publication_status": "blocked" if errors else "review-required"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}", file=sys.stderr)
    return 2 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
