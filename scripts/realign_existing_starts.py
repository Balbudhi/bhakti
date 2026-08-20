#!/usr/bin/env python3
"""Re-align existing reviewed readers with the start-only timing contract."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import bhakti_pipeline as pipeline
import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slugs, or 'all'")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--force", action="store_true", help="Ignore cached verification windows.")
    parser.add_argument("--fresh-coarse", action="store_true",
                        help="Ask for a new full-song start-only sequence instead of trusting current starts.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-existing", action="store_true",
                        help="Apply an already-reviewed start-only artifact without API calls.")
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


def occurrences_from_reader(data: dict[str, Any]) -> list[dict[str, Any]]:
    lines = data["SONG_LINES"]
    return [{"occurrence_id": f"occ-{index:03d}", "ref": entry["ref"], "repeats": int(entry.get("repeats", 1)),
             "source_text": lines[entry["ref"]].get("source", ""), "roman": lines[entry["ref"]]["roman"],
             "section": entry["section"]}
            for index, entry in enumerate(data["SONG_SEQUENCE"])]


def run_song(slug: str, options: argparse.Namespace) -> dict[str, Any]:
    song = ROOT / "songs" / slug
    path, audio = song / "data.js", pipeline.preferred_listener_audio(song)
    data = load_data(path)
    occurrences = occurrences_from_reader(data)
    duration = gemini.duration_seconds(audio)
    target = song / ".transcription" / "start-only-timing.json"
    if options.apply_existing:
        if not target.is_file():
            raise RuntimeError("no existing start-only timing artifact")
        artifact = json.loads(target.read_text(encoding="utf-8"))
        errors = artifact.get("validation_errors", [])
        sequence = artifact.get("sequence", [])
        if errors or artifact.get("publication_status") != "reviewed" or len(sequence) != len(occurrences):
            raise RuntimeError("existing start-only timing artifact is not publishable")
        data["SONG_TIMINGS"] = [{"start": entry["start"], "end": entry["end"]} for entry in sequence]
        data["SONG_META"]["timingStatus"] = "start-only-reviewed"
        write_data(path, data)
        return {"slug": slug, "status": "applied", "cost": 0.0, "entries": len(sequence), "errors": []}
    with tempfile.TemporaryDirectory(prefix="bhakti-existing-timing-") as temporary:
        model_audio = pipeline.canonical_timing_audio(audio, Path(temporary) / "timing.m4a")
        if options.fresh_coarse:
            response = gemini.call(options.model, gemini.key(), pipeline.start_only_timing_prompt(occurrences, duration),
                                   audio=model_audio, timeout=options.timeout,
                                   response_schema=pipeline.start_only_timing_schema(len(occurrences)),
                                   schema_name="bhakti_existing_fresh_starts", reasoning_effort="high",
                                   max_completion_tokens=max(16384, len(occurrences) * 256))
        else:
            response = {"packet": {"starts": [
                {"occurrence_id": occurrence["occurrence_id"], "start": data["SONG_TIMINGS"][index]["start"]}
                for index, occurrence in enumerate(occurrences)
            ], "uncertain_occurrence_ids": []}, "usage": {}, "resolved_model": "deterministic-existing-candidates"}
        coarse_sequence, errors, uncertain = pipeline.timing_sequence_from_response(
            occurrences, response["packet"], duration
        )
        sequence: list[dict[str, Any]] = []
        refinements: list[dict[str, Any]] = []
        if not errors:
            sequence, refinements, refinement_errors = pipeline.refine_all_starts(
                model_audio, occurrences, coarse_sequence, duration, options,
                song / ".transcription" / "existing-timing-windows",
            )
            errors.extend(refinement_errors)
            uncertain = []
    artifact = {"slug": slug, "model_requested": options.model, "duration_seconds": duration,
                "ordered_occurrences": occurrences, "response": response, "coarse_sequence": coarse_sequence,
                "refinements": refinements, "sequence": sequence,
                "uncertain_occurrence_ids": uncertain, "validation_errors": errors,
                "publication_status": "blocked" if errors else "reviewed"}
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if options.apply and not errors:
        data["SONG_TIMINGS"] = [{"start": entry["start"], "end": entry["end"]} for entry in sequence]
        data["SONG_META"]["timingStatus"] = "start-only-reviewed"
        write_data(path, data)
    return {"slug": slug, "status": artifact["publication_status"], "cost": pipeline.reported_cost(response, refinements),
            "entries": len(sequence), "errors": errors}


def main() -> int:
    options = parse_args()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        futures = {pool.submit(run_song, slug, options): slug for slug in slugs}
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"slug": futures[future], "status": "blocked", "error": str(exc)})
    results.sort(key=lambda item: item["slug"])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(result["status"] == "blocked" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
