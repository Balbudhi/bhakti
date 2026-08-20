#!/usr/bin/env python3
"""Deduplicate multi-pass audio evidence into a review-only karaoke timeline."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path)
    parser.add_argument("--input-dir", type=Path, help="Default: <song_dir>/.transcription")
    parser.add_argument("--tolerance-seconds", type=float, default=1.6)
    parser.add_argument("--min-support", type=int, default=2, help="Independent reports required per vocal event")
    return parser.parse_args()


def event_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("chunk-*-pass-*.json")):
        evidence = json.loads(path.read_text(encoding="utf-8"))
        chunk = evidence.get("chunk", {})
        response = evidence.get("response", {}).get("report", {})
        for event in response.get("events", []):
            if not isinstance(event, dict) or event.get("kind") == "instrumental":
                continue
            ref = event.get("match_ref")
            local_start = event.get("vocal_start")
            local_end = event.get("vocal_end")
            if not isinstance(ref, str) or not isinstance(local_start, (int, float)):
                continue
            rows.append({
                "ref": ref,
                "start": float(chunk.get("start", 0)) + float(local_start),
                "end": float(chunk.get("start", 0)) + float(local_end) if isinstance(local_end, (int, float)) else None,
                "confidence": event.get("confidence"),
                "kind": event.get("kind"),
                "heard_text": event.get("heard_text"),
                "evidence": path.name,
                "pass": evidence.get("pass_index"),
            })
    return sorted(rows, key=lambda row: (row["start"], row["ref"]))


def cluster_rows(rows: list[dict[str, Any]], tolerance: float) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for row in rows:
        if clusters:
            last = clusters[-1]
            last_center = statistics.median(item["start"] for item in last)
            if row["ref"] == last[0]["ref"] and abs(row["start"] - last_center) <= tolerance:
                last.append(row)
                continue
        clusters.append([row])
    return clusters


def summarize(clusters: list[list[dict[str, Any]]], minimum_support: int) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    findings: list[str] = []
    for cluster in clusters:
        starts = [row["start"] for row in cluster]
        ends = [row["end"] for row in cluster if isinstance(row["end"], float)]
        confidences = [float(row["confidence"]) for row in cluster if isinstance(row.get("confidence"), (int, float))]
        support = len({row["pass"] for row in cluster})
        candidate = {
            "ref": cluster[0]["ref"],
            "start": round(statistics.median(starts), 2),
            "vocal_end": round(statistics.median(ends), 2) if ends else None,
            "support": support,
            "confidence": round(statistics.mean(confidences), 3) if confidences else None,
            "heard_variants": sorted({str(row.get("heard_text") or "") for row in cluster if row.get("heard_text")}),
            "arrangements": sorted({str(row.get("kind") or "") for row in cluster}),
        "evidence": sorted(row["evidence"] for row in cluster),
            "passes": sorted({row["pass"] for row in cluster}),
        }
        if support < minimum_support:
            findings.append(f"{candidate['ref']} near {candidate['start']:.2f}s has only {support} supporting reports")
        candidates.append(candidate)
    return candidates, findings


def group_sequence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for candidate in candidates:
        if groups and groups[-1]["ref"] == candidate["ref"]:
            groups[-1]["repeats"] += 1
            groups[-1]["instances"].append(candidate)
        else:
            groups.append({"ref": candidate["ref"], "repeats": 1, "instances": [candidate]})
    for index, group in enumerate(groups):
        group["start"] = group["instances"][0]["start"]
        group["end"] = groups[index + 1]["instances"][0]["start"] if index + 1 < len(groups) else group["instances"][-1]["vocal_end"]
    return groups


def main() -> int:
    args = parse_args()
    song_dir = args.song_dir.resolve()
    input_dir = (args.input_dir or song_dir / ".transcription").resolve()
    rows = event_rows(input_dir)
    if not rows:
        raise SystemExit(f"no matched vocal events found in {input_dir}")
    candidates, findings = summarize(cluster_rows(rows, args.tolerance_seconds), args.min_support)
    groups = group_sequence(candidates)
    review_path = input_dir / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.is_file() else {}
    payload = {
        "review_required": True,
        "publish_blocked": bool(findings),
        "findings": findings,
        "unmatched_evidence": review.get("unmatched_evidence", []),
        "candidate_instances": candidates,
        "suggested_sequence_groups": groups,
        "instruction": "This is evidence, not an automatic public edit. Resolve every finding, unmatched report, lyric uncertainty, and first-vocal onset against the audio before copying a sequence or timing into data.js.",
    }
    output = input_dir / "timeline-candidates.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Candidates: {len(candidates)}; groups: {len(groups)}; findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
