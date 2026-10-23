#!/usr/bin/env python3
"""Check that retained intro and outro trim evidence was applied to the recording."""

from __future__ import annotations

import json
import hashlib
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
        if marker.get("status") == "pending":
            failures.append({"slug": review_path.parts[-3], "error": "trim transaction is incomplete"})
        elif normalized.get("validation_errors"):
            failures.append({"slug": review_path.parts[-3], "error": "trim evidence is invalid"})
        else:
            start, end = float(normalized["trim_start"]), float(normalized["trim_end"])
            needs_trim = start > 0.001 or end < float(normalized["duration"]) - 0.001
            if needs_trim and not marker.get("applied"):
                failures.append({"slug": review_path.parts[-3], "error": "verified edge material remains untrimmed",
                                 "trim_start": start, "trim_end": end})
            elif needs_trim or normalized.get("boundary_contract_version") == 2:
                try:
                    matches = (abs(float(marker.get("trim_start", -1)) - start) <= 0.001
                               and abs(float(marker.get("trim_end", -1)) - end) <= 0.001)
                except (TypeError, ValueError):
                    matches = False
                if not matches:
                    failures.append({"slug": review_path.parts[-3], "error": "applied trim interval differs from retained review"})
            if normalized.get("boundary_contract_version") == 2:
                song_dir = review_path.parent.parent
                issue = None
                if marker.get("application_version") != 2 or marker.get("source_sha256") != normalized["source_sha256"]:
                    issue = "applied trim source identity differs from reviewed original"
                outputs = marker.get("outputs", {})
                sources = pipeline.listener_audio_sources(song_dir)
                if not outputs or set(outputs) != {row["src"] for row in sources}:
                    issue = "applied trim output population differs from listener assets"
                for source in sources:
                    path = song_dir / source["src"]
                    if hashlib.sha256(path.read_bytes()).hexdigest() != outputs.get(source["src"], {}).get("sha256"):
                        issue = "listener audio digest differs from applied trim"
                if needs_trim:
                    manifest = pipeline.read_packet(review_path.parent / "trim-originals.json") or {}
                    originals = manifest.get("sources", [])
                    if manifest.get("version") != 2 or {row.get("src") for row in originals} != set(outputs):
                        issue = "trim originals manifest is missing or incomplete"
                    for row in originals:
                        name = row.get("src", "")
                        original = review_path.parent / "original-audio" / name
                        if Path(name).name != name or not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != row.get("sha256"):
                            issue = "preserved original audio digest differs from manifest"
                if issue:
                    failures.append({"slug": review_path.parts[-3], "error": issue})
    print(json.dumps({"checked": checked, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
