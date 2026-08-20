#!/usr/bin/env python3
"""Benchmark a cheaper start-only timing call against a reviewed song packet."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import bhakti_pipeline as pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("--model", default="google/gemini-3.1-flash-lite")
    parser.add_argument("--reasoning", choices=("minimal", "low", "medium", "high"), default="low")
    parser.add_argument("--timeout", type=float, default=300)
    options = parser.parse_args()

    song_dir = pipeline.ROOT / "songs" / options.slug
    audited = pipeline.read_packet(song_dir / ".transcription" / "pipeline" / "02-transcript-audit.json")
    reviewed = pipeline.read_packet(song_dir / ".transcription" / "pipeline" / "03-timing.json")
    if not audited or not reviewed or not reviewed.get("sequence"):
        available = sorted(path.parents[2].name for path in (pipeline.ROOT / "songs").glob("*/.transcription/pipeline/03-timing.json"))
        raise SystemExit("a reviewed transcript and accepted timing packet are required; available slugs: "
                         + ", ".join(available))
    occurrences = pipeline.display_occurrences(audited["packet"])
    audio = pipeline.preferred_listener_audio(song_dir)
    duration = pipeline.gemini.duration_seconds(audio)
    response = pipeline.gemini.call(
        options.model,
        pipeline.gemini.key(),
        pipeline.start_only_timing_prompt(occurrences, duration),
        audio=audio,
        timeout=options.timeout,
        response_schema=pipeline.start_only_timing_schema(len(occurrences)),
        schema_name="bhakti_timing_benchmark",
        reasoning_effort=options.reasoning,
        max_completion_tokens=max(8192, len(occurrences) * 256),
    )
    sequence, errors, uncertain = pipeline.timing_sequence_from_response(
        occurrences, response["packet"], duration
    )
    returned_starts = response["packet"].get("starts", [])
    expected = {item["occurrence_id"]: float(item["start"]) for item in reviewed["sequence"]}
    differences = [abs(float(item["start"]) - expected[item["occurrence_id"]]) for item in sequence]
    result = {
        "slug": options.slug,
        "model": options.model,
        "reasoning": options.reasoning,
        "response": response,
        "validation_errors": errors,
        "uncertain_occurrence_ids": uncertain,
        "comparison": {
            "count": len(differences),
            "expected_occurrences": len(expected),
            "returned_start_candidates": len(returned_starts),
            "returned_occurrences": len(sequence),
            "within_0_5_seconds": sum(value <= 0.5 for value in differences),
            "within_1_second": sum(value <= 1.0 for value in differences),
            "median_absolute_difference": statistics.median(differences) if differences else None,
            "max_absolute_difference": max(differences) if differences else None,
        },
    }
    name = options.model.rsplit("/", 1)[-1].replace(".", "-")
    target = song_dir / ".transcription" / "benchmarks" / f"timing-{name}-{options.reasoning}.json"
    pipeline.write_json(target, result)
    print(json.dumps({**result["comparison"], "cost": response.get("usage", {}).get("cost"),
                      "errors": errors, "uncertain": uncertain}, indent=2))
    return 1 if errors or uncertain else 0


if __name__ == "__main__":
    raise SystemExit(main())
