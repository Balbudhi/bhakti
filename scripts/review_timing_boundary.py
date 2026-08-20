#!/usr/bin/env python3
"""Precisely review one or more following-line starts with Gemini audio.

This is a focused correction tool, not another full transcription pass. Each
request contains a short clip plus the two known lyrics on either side of the
transition. The model returns only the following line's first-syllable start.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song", help="Song slug")
    parser.add_argument("indices", nargs="+", type=int, help="Preceding SONG_SEQUENCE indices")
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--radius", type=float, default=10.0)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--max-spread", type=float, default=0.35)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def load_data(path: Path) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    return json.loads(subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout)


def write_data(path: Path, data: dict[str, Any]) -> None:
    content = ("window.SONG_META = " + json.dumps(data["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_LINES = " + json.dumps(data["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_SEQUENCE = " + json.dumps(data["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_TIMINGS = " + json.dumps(data["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n")
    path.write_text(content, encoding="utf-8")


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def review_boundary(song: Path, data: dict[str, Any], index: int, options: argparse.Namespace, temp: Path) -> dict[str, Any]:
    sequence, timings, lines = data["SONG_SEQUENCE"], data["SONG_TIMINGS"], data["SONG_LINES"]
    if not 0 <= index < len(sequence) - 1:
        raise RuntimeError(f"boundary index {index} is outside the sequence")
    previous, following = sequence[index], sequence[index + 1]
    proposed = float(timings[index + 1]["start"])
    duration = gemini.duration_seconds(song / "audio.m4a")
    clip_start, clip_end = max(0.0, proposed - options.radius), min(duration, proposed + options.radius)
    clip = temp / f"boundary-{index:03d}.m4a"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{clip_start:.3f}",
                    "-i", str(song / "audio.m4a"), "-t", f"{clip_end - clip_start:.3f}", "-vn",
                    "-c:a", "aac", "-b:a", "192k", str(clip)], check=True)
    before = lines[previous["ref"]]
    after = lines[following["ref"]]
    prompt = f"""Find one known lyric start in this short devotional-song excerpt. The lyrics and their order below are already correct. Do not transcribe, correct, identify, reorder, group, explain, or estimate from rhythm.

The attached clip is source seconds {clip_start:.3f}–{clip_end:.3f}. Return times RELATIVE TO THIS CLIP.

PRECEDING displayed lyric (immediate contiguous repeats: {previous.get('repeats', 1)}):
source: {before.get('source', '')}
roman: {before.get('roman', '')}

FOLLOWING displayed lyric (immediate contiguous repeats: {following.get('repeats', 1)}):
source: {after.get('source', '')}
roman: {after.get('roman', '')}

The old proposed transition was source second {proposed:.3f}; it is known to be only a candidate and may be early or late.

Your only task is to return `following_start`: the exact relative second at the FIRST AUDIBLE SYLLABLE of the FOLLOWING lyric's first repetition. Do not use the middle of that line, a response, or a later repetition. Mark uncertainty rather than guessing.

Return strict JSON:
{{"following_ref":"{following['ref']}","following_start":0.0,"uncertainty":""}}"""
    attempts: list[dict[str, Any]] = []
    for run in range(max(1, options.passes)):
        try:
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout)
            packet = response["packet"]
        except RuntimeError as exc:
            attempts.append({
                "run": run + 1,
                "following_start": round(proposed, 3),
                "response": {"error": str(exc)},
                "validation_errors": ["model did not return usable JSON"],
            })
            continue
        errors: list[str] = []
        if packet.get("following_ref") != following["ref"]:
            errors.append("response ref does not match the requested following line")
        try:
            following_start = clip_start + float(packet["following_start"])
            if not clip_start <= following_start <= clip_end:
                errors.append("measured start falls outside the clip")
        except (KeyError, TypeError, ValueError):
            following_start = proposed
            errors.append("response lacks a numeric following start")
        if str(packet.get("uncertainty", "")).strip().casefold() not in {"", "none", "no", "null", "n/a"}:
            errors.append("following start remains uncertain")
        attempts.append({
            "run": run + 1,
            "following_start": round(following_start, 3),
            "response": response,
            "validation_errors": errors,
        })
    valid = [attempt for attempt in attempts if not attempt["validation_errors"]]
    errors: list[str] = []
    if not valid:
        following_start = proposed
        response = attempts[-1]["response"]
        errors.append("no valid following-start passes")
    else:
        starts = [attempt["following_start"] for attempt in valid]
        following_start = round(median(starts), 3)
        if max(starts) - min(starts) > options.max_spread:
            errors.append("following-start spread exceeds consensus threshold")
        response = min(valid, key=lambda attempt: abs(attempt["following_start"] - following_start))["response"]
    return {"index": index, "clip": {"start": clip_start, "end": clip_end}, "old_transition": proposed,
            "following_start": round(following_start, 3),
            "attempts": attempts, "response": response, "validation_errors": errors, "status": "blocked" if errors else "reviewed"}


def main() -> int:
    options = parse_args()
    song = ROOT / "songs" / options.song
    data_path = song / "data.js"
    data = load_data(data_path)
    output = song / ".transcription" / "boundary-review"
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    with tempfile.TemporaryDirectory(prefix="bhakti-boundary-") as temporary:
        for index in options.indices:
            report = review_boundary(song, data, index, options, Path(temporary))
            (output / f"boundary-{index:03d}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            reports.append(report)
    if options.apply:
        errors = [error for report in reports for error in report["validation_errors"]]
        if errors:
            raise SystemExit("refusing to apply blocked boundary review")
        for report in reports:
            index = report["index"]
            data["SONG_TIMINGS"][index]["end"] = report["following_start"]
            data["SONG_TIMINGS"][index + 1]["start"] = report["following_start"]
        write_data(data_path, data)
    print(json.dumps([{key: report[key] for key in ("index", "old_transition", "following_start", "status", "validation_errors")} for report in reports], ensure_ascii=False, indent=2))
    return 1 if any(report["status"] == "blocked" for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
