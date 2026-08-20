#!/usr/bin/env python3
"""Run a third, audio-backed audit of two Bhakti transcription passes.

The output is review evidence only. It never alters lyrics, timings, credits,
or audio files, and it never treats an intro/outro trim proposal as automatic.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import transcribe_bhakti_openrouter as workflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path)
    parser.add_argument("--model", default=workflow.DEFAULT_MODEL)
    parser.add_argument("--chunk-seconds", type=float, default=42.0)
    parser.add_argument("--overlap-seconds", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--key-file", type=Path)
    return parser.parse_args()


def prompt_for(chunk: workflow.Chunk, candidates: list[dict[str, Any]], unmatched: list[dict[str, Any]], lines: dict[str, str], duration: float) -> str:
    local_candidates = [
        {"ref": item["ref"], "predicted_vocal_start": item["start"], "heard_variants": item["heard_variants"]}
        for item in candidates
        if chunk.start - 1.0 <= item["start"] <= chunk.end + 1.0
    ]
    local_unmatched = [item for item in unmatched if chunk.start - 1.0 <= item.get("absolute_start", -9999) <= chunk.end + 1.0]
    catalogue = "\n".join(f"- {ref}: {roman}" for ref, roman in lines.items()) or "(raw transcription; no site catalogue yet)"
    trim_scope = "opening" if chunk.start == 0 else "ending" if chunk.end >= duration - 0.01 else "middle"
    return f"""Audit a proposed karaoke transcript against the attached audio chunk ({chunk.start:.2f}s–{chunk.end:.2f}s of the source). Return strict JSON only.

This is the third pass after two independent transcriptions. Do not assume any vocal arrangement, language, singer identity, or lyric order. A displayed line begins at its first audible vocal instantiation. Every timestamp you return must be an **absolute source-recording second** in the range {chunk.start:.2f}–{chunk.end:.2f}, never a chunk-local offset.

Known catalogue:
{catalogue}

Candidate vocal instances in this chunk:
{json.dumps(local_candidates, ensure_ascii=False)}

Unmatched/uncertain evidence from the first two passes (must be checked, never ignored):
{json.dumps(local_unmatched, ensure_ascii=False)}

Check every candidate against the audio. Report every missing vocal instance, every changed lyric, every wrong order, and every onset that should move by more than 0.5 seconds. For this {trim_scope} chunk, identify non-song spoken/platform material or silence before/after the actual performance, but do not call a musical introduction/outro disposable merely because it has no words.

Return exactly:
{{"events":[{{"vocal_start":0.0,"vocal_end":0.0,"heard_text":"...","match_ref":"catalogue_ref or null","kind":"solo|duet|choir|spoken|call_response|instrumental|uncertain","confidence":0.0,"note":"confirmed candidate | missing candidate | corrected onset | new instance | lyric discrepancy"}}],"issues":["..."],"trim_assessment":{{"recommended":false,"content_start":null,"content_end":null,"reason":"..."}}}}
"""


def main() -> int:
    args = parse_args()
    song_dir = args.song_dir.resolve()
    audio = song_dir / "audio.m4a"
    data = song_dir / "data.js"
    evidence_dir = song_dir / ".transcription"
    candidates_path = evidence_dir / "timeline-candidates.json"
    if not audio.is_file() or not candidates_path.is_file():
        raise SystemExit("run the two transcription passes and summarizer first")
    lines, _ = workflow.parse_song_data(data if data.is_file() else None)
    candidate_data = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = candidate_data.get("candidate_instances", [])
    unmatched = candidate_data.get("unmatched_evidence", [])
    duration = workflow.probe_duration(audio)
    api_key = workflow.read_api_key(args.key_file)
    output_dir = evidence_dir / "reconciliation"
    output_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-reconcile-") as temporary:
        chunks = workflow.create_chunks(audio, duration, args.chunk_seconds, args.overlap_seconds, Path(temporary))
        for chunk in chunks:
            print(f"Reconciling chunk {chunk.index + 1}/{len(chunks)}…", file=sys.stderr)
            response = workflow.send_request(api_key, args.model, chunk.path, prompt_for(chunk, candidates, unmatched, lines, duration), args.timeout)
            artifact: dict[str, Any] = {
                "source_audio": str(audio),
                "model_requested": args.model,
                "chunk": {"index": chunk.index, "start": chunk.start, "end": chunk.end},
                "response": response,
            }
            (output_dir / f"chunk-{chunk.index:03d}.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reconciliation evidence to {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
