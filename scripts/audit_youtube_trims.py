#!/usr/bin/env python3
"""Fail closed when retained trim evidence says a YouTube intro must be removed."""

from __future__ import annotations

import json
from pathlib import Path

import bhakti_pipeline as pipeline


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failures = []
    checked = 0
    for review_path in sorted((ROOT / "songs").glob("*/.transcription/trim-review.json")):
        artifact = pipeline.read_packet(review_path)
        if not artifact or "start" not in artifact or "end" not in artifact:
            continue
        checked += 1
        normalized = pipeline.normalize_trim_artifact(artifact)
        marker = pipeline.read_packet(review_path.parent / "trim-applied.json") or {}
        if normalized.get("validation_errors"):
            failures.append({"slug": review_path.parts[-3], "error": "trim evidence is invalid"})
        elif float(normalized["trim_start"]) > 0.001 and not marker.get("applied"):
            failures.append({"slug": review_path.parts[-3], "error": "verified leading intro remains untrimmed",
                             "trim_start": normalized["trim_start"]})
    print(json.dumps({"checked": checked, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
