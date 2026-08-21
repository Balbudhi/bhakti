#!/usr/bin/env python3
"""Recover only the six held timing onsets in Hariharan's Hanuman Bhajan.

This command deliberately does *not* invoke the normal timing pipeline.  That
pipeline would derive new windows for all 240 occurrences and could overwrite
valid bounded evidence.  Instead it uses the accepted neighbouring onsets
already present in the blocked packet to make four narrowly-scoped requests:

* one two-line recovery for occurrences 046/047;
* one evidence-preserving check for 142 (which may be absent in the recording);
* one recovery each for 179 and 229.

Occurrence 144 is not sent again: its two existing bounded responses already
agree within 0.20 seconds and can be accepted by a separate, reviewed
deterministic repair.  ``--execute`` requires an intentionally awkward
confirmation token.  Without it the program merely prints the exact bounded
request plan and makes no network or filesystem changes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]
SLUG = "hanuman-bhajan-hariharan"
CONFIRMATION = "HARIHARAN-SIX-HOLD-RECOVERY"
TIMING_PATH = ROOT / "songs" / SLUG / ".transcription" / "pipeline" / "03-timing.json"
AUDIO_PATH = ROOT / "songs" / SLUG / "audio.m4a"
REPORT_PATH = ROOT / "songs" / SLUG / ".transcription" / "pipeline" / "hariharan-bounded-recovery.json"


# Each clip is deliberately bracketed by starts that survived the long-window
# contract.  Do not replace these with stale coarse candidates.
RECOVERIES = (
    {
        "id": "occ-046-047",
        "targets": ("occ-046", "occ-047"),
        "clip_start": 356.0,
        "clip_end": 383.0,
        "lower_id": "occ-045",
        "upper_id": "occ-048",
        "expected_lower": 361.969,
        "expected_upper": 377.920,
        "context": "Both missing lines occur between two accepted lines; return both starts in order.",
    },
    {
        "id": "occ-142",
        "targets": ("occ-142",),
        "clip_start": 1319.0,
        "clip_end": 1373.0,
        "lower_id": "occ-141",
        "upper_id": "occ-144",
        "expected_lower": 1323.350,
        "expected_upper": 1367.130,
        "context": (
            "Occurrence 143 may be omitted by this recording. Determine only whether 142 is sung; "
            "do not substitute 143 or 144 for it."
        ),
        "allow_not_sung": True,
    },
    {
        "id": "occ-179",
        "targets": ("occ-179",),
        "clip_start": 1788.0,
        "clip_end": 1804.0,
        "lower_id": "occ-178",
        "upper_id": "occ-180",
        "expected_lower": 1790.950,
        "expected_upper": 1800.764,
        "context": "Return the one target onset between the accepted adjacent lines.",
    },
    {
        "id": "occ-229",
        "targets": ("occ-229",),
        "clip_start": 2232.0,
        "clip_end": 2252.0,
        "lower_id": "occ-228",
        "upper_id": "occ-230",
        "expected_lower": 2234.290,
        "expected_upper": 2249.406,
        "context": "Return the one target onset between the accepted adjacent lines.",
    },
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected an object in {path}")
    return value


def accepted_starts(packet: dict[str, Any]) -> dict[str, float]:
    """Return the starts accepted by existing bounded reports only."""
    starts: dict[str, float] = {}
    for report in packet.get("refinements", []):
        uncertain = {str(value) for value in report.get("uncertain_ids", [])}
        for item in report.get("starts", []):
            occurrence_id = str(item.get("occurrence_id", ""))
            if occurrence_id and occurrence_id not in uncertain:
                starts.setdefault(occurrence_id, float(item["start"]))
    return starts


def held_ids(packet: dict[str, Any]) -> set[str]:
    prefix = "occ-"
    ids: set[str] = set()
    for error in packet.get("validation_errors", []):
        text = str(error)
        if text.startswith(prefix) and ":" in text:
            ids.add(text.split(":", 1)[0])
    return ids


def occurrences_by_id(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    occurrences = packet.get("ordered_occurrences")
    if not isinstance(occurrences, list):
        raise RuntimeError("timing packet has no ordered occurrences")
    result = {str(item.get("occurrence_id")): item for item in occurrences if isinstance(item, dict)}
    if len(result) != len(occurrences):
        raise RuntimeError("timing packet contains duplicate or malformed occurrence IDs")
    return result


def verify_packet(packet: dict[str, Any]) -> dict[str, float]:
    if packet.get("publication_status") != "blocked":
        raise RuntimeError("refusing recovery: Hariharan timing packet is no longer blocked")
    expected_holds = {"occ-046", "occ-047", "occ-142", "occ-144", "occ-179", "occ-229"}
    observed_holds = held_ids(packet)
    if observed_holds != expected_holds:
        raise RuntimeError(f"refusing recovery: expected exact held IDs {sorted(expected_holds)}, got {sorted(observed_holds)}")
    starts = accepted_starts(packet)
    for spec in RECOVERIES:
        lower, upper = spec["lower_id"], spec["upper_id"]
        if lower not in starts or upper not in starts:
            raise RuntimeError(f"refusing recovery: {spec['id']} has no accepted neighbour bracket")
        if abs(starts[lower] - spec["expected_lower"]) > 0.01 or abs(starts[upper] - spec["expected_upper"]) > 0.01:
            raise RuntimeError(f"refusing recovery: {spec['id']} neighbour evidence changed")
        if not starts[lower] < starts[upper]:
            raise RuntimeError(f"refusing recovery: invalid neighbour order for {spec['id']}")
    return starts


def response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "starts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "occurrence_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["found", "not_sung", "uncertain"]},
                        "start": {"type": "number"},
                        "uncertainty": {"type": "string"},
                    },
                    "required": ["occurrence_id", "status", "start", "uncertainty"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["starts"],
        "additionalProperties": False,
    }


def prompt_for(spec: dict[str, Any], occurrences: dict[str, dict[str, Any]]) -> str:
    targets = [occurrences[occurrence_id] for occurrence_id in spec["targets"]]
    preceding = occurrences[spec["lower_id"]]
    following = occurrences[spec["upper_id"]]
    duration = spec["clip_end"] - spec["clip_start"]
    return f"""This is a narrow, lyric-aware onset-verification task. Do not transcribe, rewrite, reorder, explain, or infer a canonical reading.

The attached audio is exactly source seconds {spec['clip_start']:.3f}–{spec['clip_end']:.3f}. Return times RELATIVE TO THIS CLIP, between 0 and {duration:.3f}.
The two lines surrounding this exact interval have independently accepted starts:
PRECEDING: {json.dumps(preceding, ensure_ascii=False)} at source {spec['expected_lower']:.3f}s
FOLLOWING: {json.dumps(following, ensure_ascii=False)} at source {spec['expected_upper']:.3f}s
TARGETS IN REQUIRED ORDER: {json.dumps(targets, ensure_ascii=False)}

{spec['context']}

For every requested target, return exactly one item and preserve target order. `found` means the target's first audible syllable is present: report that onset. `not_sung` is allowed only when the target genuinely is absent from this recording: use start -1. `uncertain` is allowed only when you cannot distinguish it: use start -1. Never use the preceding or following line's onset for a target.

Return strict JSON only: {{"starts":[{{"occurrence_id":"{spec['targets'][0]}","status":"found","start":0.0,"uncertainty":""}}]}}"""


def validate_attempt(spec: dict[str, Any], packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = packet.get("starts")
    targets = list(spec["targets"])
    if not isinstance(values, list) or [item.get("occurrence_id") for item in values if isinstance(item, dict)] != targets:
        raise RuntimeError(f"{spec['id']}: response did not preserve the exact target order")
    validated: dict[str, dict[str, Any]] = {}
    local_duration = spec["clip_end"] - spec["clip_start"]
    for item in values:
        if not isinstance(item, dict):
            raise RuntimeError(f"{spec['id']}: malformed response item")
        occurrence_id, status, local_start = item["occurrence_id"], item["status"], float(item["start"])
        if status == "found":
            source_start = spec["clip_start"] + local_start
            if not 0.0 <= local_start <= local_duration:
                raise RuntimeError(f"{spec['id']} {occurrence_id}: returned time outside clip")
            if not spec["expected_lower"] < source_start < spec["expected_upper"]:
                raise RuntimeError(f"{spec['id']} {occurrence_id}: returned time outside accepted neighbour bracket")
            validated[occurrence_id] = {"status": status, "start": round(source_start, 3),
                                        "uncertainty": str(item.get("uncertainty", ""))}
        else:
            if status == "not_sung" and not spec.get("allow_not_sung"):
                raise RuntimeError(f"{spec['id']} {occurrence_id}: not_sung is not permitted for this recovery")
            if local_start != -1:
                raise RuntimeError(f"{spec['id']} {occurrence_id}: non-found result must use start -1")
            validated[occurrence_id] = {"status": status, "start": None,
                                        "uncertainty": str(item.get("uncertainty", ""))}
    return validated


def two_pass_consensus(spec: dict[str, Any], attempts: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    if len(attempts) != 2:
        raise RuntimeError(f"{spec['id']}: requires exactly two attempts")
    consensus: dict[str, dict[str, Any]] = {}
    for occurrence_id in spec["targets"]:
        first, second = attempts[0][occurrence_id], attempts[1][occurrence_id]
        if first["status"] != second["status"]:
            raise RuntimeError(f"{spec['id']} {occurrence_id}: independent attempts disagree on status")
        if first["status"] == "found":
            if abs(float(first["start"]) - float(second["start"])) > 0.5:
                raise RuntimeError(f"{spec['id']} {occurrence_id}: independent starts differ by more than 0.5s")
            consensus[occurrence_id] = {"status": "found", "start": round((float(first["start"]) + float(second["start"])) / 2, 3),
                                        "measurements": [first["start"], second["start"]]}
        elif first["status"] == "not_sung":
            consensus[occurrence_id] = {"status": "not_sung", "start": None,
                                        "measurements": [None, None]}
        else:
            raise RuntimeError(f"{spec['id']} {occurrence_id}: unresolved uncertainty is not a repair")
    return consensus


def dry_run_plan(packet: dict[str, Any]) -> dict[str, Any]:
    starts = verify_packet(packet)
    occurrences = occurrences_by_id(packet)
    return {
        "slug": SLUG,
        "mode": "dry-run",
        "network_calls": 0,
        "exact_future_audio_calls": 8,
        "deterministic_existing_evidence": {
            "occ-144": {
                "measurements": [1367.03, 1367.23],
                "consensus": 1367.13,
                "bracket": [starts["occ-141"], starts["occ-145"]],
                "reason": "two pre-existing independent bounded responses agree within 0.20s",
            },
        },
        "recoveries": [{
            "id": spec["id"], "targets": list(spec["targets"]),
            "source_clip": [spec["clip_start"], spec["clip_end"]],
            "accepted_neighbour_bracket": [starts[spec["lower_id"]], starts[spec["upper_id"]]],
            "calls": 2, "prompt": prompt_for(spec, occurrences),
        } for spec in RECOVERIES],
    }


def make_clip(spec: dict[str, Any], destination: Path) -> Path:
    output = destination / f"{spec['id']}.m4a"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{spec['clip_start']:.3f}",
        "-i", str(AUDIO_PATH), "-t", f"{spec['clip_end'] - spec['clip_start']:.3f}",
        "-vn", "-c:a", "aac", "-b:a", "192k", str(output),
    ], check=True)
    return output


def execute(packet: dict[str, Any], *, model: str, timeout: float) -> dict[str, Any]:
    verify_packet(packet)
    occurrences = occurrences_by_id(packet)
    if not AUDIO_PATH.is_file():
        raise RuntimeError(f"missing local audio: {AUDIO_PATH}")
    report: dict[str, Any] = {
        "slug": SLUG,
        "mode": "executed",
        "model_requested": model,
        "timing_packet": str(TIMING_PATH.relative_to(ROOT)),
        "audio": str(AUDIO_PATH.relative_to(ROOT)),
        "recoveries": [],
        "deterministic_existing_evidence": {
            "occ-144": {"measurements": [1367.03, 1367.23], "consensus": 1367.13,
                        "rule": "two existing bounded responses agree within 0.5 seconds and lie between accepted neighbours"},
        },
    }
    with tempfile.TemporaryDirectory(prefix="bhakti-hariharan-six-holds-") as raw:
        temporary = Path(raw)
        for spec in RECOVERIES:
            clip = make_clip(spec, temporary)
            attempts: list[dict[str, dict[str, Any]]] = []
            evidence: list[dict[str, Any]] = []
            for index in range(2):
                response = gemini.call(
                    model, gemini.key(), prompt_for(spec, occurrences), audio=clip, timeout=timeout,
                    response_schema=response_schema(), schema_name="bhakti_hariharan_bounded_recovery",
                    reasoning_effort="high", max_completion_tokens=2048,
                )
                validated = validate_attempt(spec, response["packet"])
                attempts.append(validated)
                evidence.append({"attempt": index + 1, "result": validated, "usage": response.get("usage", {}),
                                 "resolved_model": response.get("resolved_model")})
            report["recoveries"].append({
                "id": spec["id"], "targets": list(spec["targets"]),
                "source_clip": [spec["clip_start"], spec["clip_end"]],
                "accepted_neighbour_bracket": [spec["expected_lower"], spec["expected_upper"]],
                "attempts": evidence,
                "consensus": two_pass_consensus(spec, attempts),
            })
    cost = 0.0
    cost_seen = False
    for recovery in report["recoveries"]:
        for attempt in recovery["attempts"]:
            value = attempt["usage"].get("cost") if isinstance(attempt.get("usage"), dict) else None
            if isinstance(value, (int, float)):
                cost += float(value)
                cost_seen = True
    report["reported_openrouter_cost"] = round(cost, 8) if cost_seen else None
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Perform exactly the eight bounded audio calls.")
    parser.add_argument("--confirm", help=f"Required with --execute: {CONFIRMATION}")
    parser.add_argument("--model", default="google/gemini-3.7-flash")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    packet = read_json(TIMING_PATH)
    if not args.execute:
        print(json.dumps(dry_run_plan(packet), ensure_ascii=False, indent=2))
        return 0
    if args.confirm != CONFIRMATION:
        parser.error(f"--execute requires --confirm {CONFIRMATION}")
    result = execute(packet, model=args.model, timeout=args.timeout)
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH.relative_to(ROOT)),
                      "reported_openrouter_cost": result["reported_openrouter_cost"],
                      "consensus": [item["consensus"] for item in result["recoveries"]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
