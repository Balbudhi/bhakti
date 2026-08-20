#!/usr/bin/env python3
"""One lyric-aware timing pass, windowed only for timestamp precision.

Each window is sent once to Gemini; overlap is merged locally. This is not a
second transcription pass. It is the timing stage for recordings too long for
reliable single-request timestamps.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import align_song_lyrics as catalogue
import process_song_gemini as gemini


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path)
    parser.add_argument("--window-seconds", type=float, default=55)
    parser.add_argument("--overlap-seconds", type=float, default=2)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=180)
    return parser.parse_args()


def windows(audio: Path, duration: float, width: float, overlap: float, destination: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    core_start = 0.0
    index = 0
    while core_start < duration - 0.01:
        start = max(0.0, core_start - overlap)
        end = min(duration, core_start + width + overlap)
        path = destination / f"window-{index:03d}.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio), "-ss", f"{start:.3f}", "-t", f"{end-start:.3f}", "-vn", "-c:a", "aac", "-b:a", "128k", str(path)], check=True)
        result.append({"index": index, "start": start, "end": end, "path": path})
        core_start += width
        index += 1
    return result


def merge(events: list[dict[str, Any]], duration: float) -> tuple[list[dict[str, Any]], list[str]]:
    events.sort(key=lambda item: (item["start"], item["ref"]))
    merged: list[dict[str, Any]] = []
    errors: list[str] = []
    for event in events:
        if not 0 <= event["start"] <= event["end"] <= duration:
            errors.append(f"out-of-range event {event['ref']} at {event['start']}")
            continue
        if merged and event["ref"] == merged[-1]["ref"] and abs(event["start"] - merged[-1]["start"]) < 2.0:
            merged[-1]["start"] = round(statistics.median([merged[-1]["start"], event["start"]]), 2)
            merged[-1]["end"] = max(merged[-1]["end"], event["end"])
            merged[-1]["repeats"] = max(merged[-1]["repeats"], event["repeats"])
            merged[-1]["evidence"].append(event["window"])
            continue
        event["evidence"] = [event.pop("window")]
        merged.append(event)
    for index, entry in enumerate(merged):
        entry["end"] = merged[index + 1]["start"] if index + 1 < len(merged) else min(duration, entry["end"])
    return merged, errors


def main() -> int:
    options = parse_args()
    song = options.song_dir.resolve()
    audio, data = song / "audio.m4a", song / "data.js"
    if not audio.is_file() or not data.is_file():
        raise SystemExit("song directory needs audio.m4a and data.js")
    lines = catalogue.line_catalog(data)
    duration = gemini.duration_seconds(audio)
    output_dir = song / ".transcription" / "window-alignment"
    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = gemini.key()
    events: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="bhakti-timing-") as temp:
        for window in windows(audio, duration, options.window_seconds, options.overlap_seconds, Path(temp)):
            local_duration = window["end"] - window["start"]
            prompt = f"""Align this short audio window to the canonical lyric catalogue. This is window {window['index']} of a single timing pass. Its audio starts at source {window['start']:.3f}s and ends at source {window['end']:.3f}s. Return timestamps RELATIVE TO THIS WINDOW (0 to {local_duration:.3f}), never source-absolute timestamps.

Capture every first audible syllable for every lyric in the window. Map only exact canonical refs. Do not invent a line or turn a phrase fragment into a full line. If audio cannot map exactly, place it in unmatched. `repeats` is only for immediately contiguous exact instances.

Catalogue:
{json.dumps(lines, ensure_ascii=False)}

Return strict JSON: {{"events":[{{"ref":"catalogue-id","repeats":1,"start":0.0,"end":0.0,"note":""}}],"unmatched":[{{"start":0.0,"end":0.0,"heard":""}}]}}."""
            response = gemini.call(options.model, api_key, prompt, audio=window["path"], timeout=options.timeout)
            artifact = {"window": {key: value for key, value in window.items() if key != "path"}, "response": response}
            (output_dir / f"window-{window['index']:03d}.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for raw in response["packet"].get("events", []):
                if raw.get("ref") not in lines:
                    unmatched.append({"window": window["index"], "event": raw})
                    continue
                try:
                    events.append({"ref": raw["ref"], "repeats": int(raw.get("repeats", 1)), "start": window["start"] + float(raw["start"]), "end": window["start"] + float(raw["end"]), "window": window["index"]})
                except (KeyError, TypeError, ValueError):
                    unmatched.append({"window": window["index"], "event": raw})
            unmatched.extend({"window": window["index"], "event": raw} for raw in response["packet"].get("unmatched", []))
    sequence, errors = merge(events, duration)
    expected = set(lines)
    found = {entry["ref"] for entry in sequence}
    missing = sorted(expected - found)
    if missing:
        errors.append(f"catalogue lines not heard: {', '.join(missing)}")
    if unmatched:
        errors.append("unmatched audible material requires review")
    packet = {"model_requested": options.model, "duration_seconds": duration, "sequence": sequence, "unmatched": unmatched, "validation_errors": errors, "publication_status": "blocked" if errors else "review-required"}
    target = output_dir / "alignment.json"
    target.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
