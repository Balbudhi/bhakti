#!/usr/bin/env python3
"""Produce reviewable vocal transcription evidence for any song.

This intentionally does not edit data.js. It sends overlapping audio chunks and
an optional lyric catalogue to an audio-capable Google Gemini Flash model via
OpenRouter, then records every raw pass plus a deterministic coverage report.
Reviewers use that evidence to correct lyric inventory, order, and timings.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "google/gemini-3.6-flash"
DEFAULT_KEY_FILE = Path.home() / "Dev" / "openrouter.key"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class Chunk:
    index: int
    start: float
    end: float
    path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("song_dir", type=Path, help="Directory containing audio.m4a and data.js")
    parser.add_argument("--audio", type=Path, help="Override the audio path (default: <song_dir>/audio.m4a)")
    parser.add_argument("--data", type=Path, help="Override the data path (default: <song_dir>/data.js)")
    parser.add_argument("--output-dir", type=Path, help="Default: <song_dir>/.transcription")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"OpenRouter model (default: {DEFAULT_MODEL})")
    parser.add_argument("--passes", type=int, default=2, help="Independent analyses of each chunk (default: 2; reconcile separately)")
    parser.add_argument("--chunk-seconds", type=float, default=42.0, help="Core chunk duration (default: 42)")
    parser.add_argument("--overlap-seconds", type=float, default=2.0, help="Context overlap on both sides (default: 2)")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout in seconds (default: 180)")
    parser.add_argument("--key-file", type=Path, help="Read key from this owner-only file instead of the Dev default")
    return parser.parse_args()


def read_api_key(key_file: Path | None) -> str:
    """Read a key without emitting it or placing it in a shell environment."""
    direct = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if direct:
        return direct
    requested_path = os.environ.get("OPENROUTER_API_KEY_FILE", "").strip()
    path = key_file or (Path(requested_path).expanduser() if requested_path else DEFAULT_KEY_FILE)
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise RuntimeError(f"refusing insecure key file permissions {mode:03o}: {path}")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"OpenRouter credential unavailable at {path}; set OPENROUTER_API_KEY or OPENROUTER_API_KEY_FILE") from exc
    if not value:
        raise RuntimeError(f"OpenRouter credential file is empty: {path}")
    return value


def probe_duration(audio: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(audio)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def parse_song_data(data_path: Path | None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if data_path is None:
        return {}, []
    source = data_path.read_text(encoding="utf-8")
    lines = dict(re.findall(r"^\s{2}([A-Za-z0-9_]+):\s*\{\s*$[\s\S]*?^\s{4}roman:\s*\"([^\"]+)\"", source, flags=re.MULTILINE))
    sequence_region = re.search(r"window\.SONG_SEQUENCE\s*=\s*\[([\s\S]*?)\n\];", source)
    if not lines or not sequence_region:
        raise RuntimeError(f"could not parse SONG_LINES and SONG_SEQUENCE from {data_path}")
    sequence: list[dict[str, Any]] = []
    for block in re.findall(r"\{([\s\S]*?)\}", sequence_region.group(1)):
        ref = re.search(r"\bref:\s*\"([^\"]+)\"", block)
        if not ref:
            continue
        repeats = re.search(r"\brepeats:\s*(\d+)", block)
        sequence.append({"ref": ref.group(1), "repeats": int(repeats.group(1)) if repeats else 1})
    if not sequence or any(item["ref"] not in lines for item in sequence):
        raise RuntimeError(f"invalid sequence in {data_path}")
    return lines, sequence


def create_chunks(audio: Path, duration: float, core_seconds: float, overlap: float, temp_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    cursor = 0.0
    index = 0
    while cursor < duration - 0.01:
        start = max(0.0, cursor - overlap)
        end = min(duration, cursor + core_seconds + overlap)
        target = temp_dir / f"chunk-{index:03d}.m4a"
        # Output-side seeking plus re-encoding makes chunk time zero correspond
        # to the declared source offset. Stream-copy seeks M4A/AAC only at
        # packet/keyframe boundaries, which is too imprecise for lyric onsets.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio), "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-vn", "-c:a", "aac", "-b:a", "128k", str(target)], check=True)
        chunks.append(Chunk(index=index, start=start, end=end, path=target))
        cursor += core_seconds
        index += 1
    return chunks


def prompt_for(chunk: Chunk, lines: dict[str, str], sequence: list[dict[str, Any]]) -> str:
    catalogue = "\n".join(f"- {ref}: {roman}" for ref, roman in lines.items()) or "(No catalogue has been supplied. Produce a raw transcription.)"
    expected = " -> ".join(f"{item['ref']}×{item['repeats']}" for item in sequence) or "(No site sequence exists yet; establish the raw vocal order.)"
    return f"""You are auditing a devotional-song karaoke reader. Analyze only the attached audio chunk, which spans absolute {chunk.start:.2f}s to {chunk.end:.2f}s of the recording. Return strict JSON, no Markdown.

Critical rules:
1. Capture every audible vocal line or pickup in performance order, regardless of solo, duet, choir, spoken, call-and-response, or any other arrangement. Do not assume a lead/chorus structure.
2. Timestamp each event relative to this supplied chunk, to 0.1 seconds. `vocal_start` is the first audible syllable of that exact lyric instance, not where a later singer or chorus becomes clear.
3. Match an event to the catalogue only when the audio supports it. Never force a match. For an absent, changed, or uncertain lyric use `match_ref: null` and give the literal heard text plus a concise uncertainty note.
4. A return to a previously sung line after a different line is a new event. Do not collapse it into a repeat count.
5. Check for early pickups, responses, overlaps, and returning lines. Do not report invented words.

Known line catalogue:
{catalogue}

The site currently *claims* this broad order; treat it as a hypothesis to audit, not as truth:
{expected}

Return exactly this shape:
{{"events":[{{"vocal_start":0.0,"vocal_end":0.0,"heard_text":"...","match_ref":"catalogue_ref or null","kind":"solo|duet|choir|spoken|call_response|instrumental|uncertain","confidence":0.0,"note":"..."}}],"chunk_notes":["..."]}}
"""


def send_request(api_key: str, model: str, audio_path: Path, prompt: str, timeout: float) -> dict[str, Any]:
    audio_bytes = audio_path.read_bytes()
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio_bytes).decode("ascii"), "format": "m4a"}},
        ]}],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vedanta.eeshan.xyz/",
            "X-Title": "Vedanta Timeline Bhakti transcription review",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"OpenRouter returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc.reason}") from exc
    try:
        content = answer["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str):
            raise TypeError("response content was not text")
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("events"), list):
            raise ValueError("response lacks events[]")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("model response was not the requested JSON event report") from exc
    return {"report": parsed, "usage": answer.get("usage", {}), "model": answer.get("model", model)}


def review_reports(reports: list[dict[str, Any]], duration: float, sequence: list[dict[str, Any]]) -> dict[str, Any]:
    expected_refs = [entry["ref"] for entry in sequence]
    findings: list[str] = []
    matched: dict[str, int] = {f"{index}:{ref}": 0 for index, ref in enumerate(expected_refs)}
    per_pass: dict[str, list[float]] = {}
    unmatched_evidence: list[dict[str, Any]] = []
    for item in reports:
        chunk_start = item["chunk"]["start"]
        last_start = -1.0
        for event in sorted(item["response"]["report"].get("events", []), key=lambda value: value.get("vocal_start", -1)):
            if not isinstance(event, dict):
                findings.append("a response included a non-object event")
                continue
            ref = event.get("match_ref")
            local_start = event.get("vocal_start")
            if not isinstance(local_start, (int, float)):
                findings.append(f"missing vocal_start in chunk {item['chunk']['index']}")
                continue
            absolute_start = chunk_start + float(local_start)
            matching_positions = [index for index, expected_ref in enumerate(expected_refs) if expected_ref == ref]
            if matching_positions:
                for position in matching_positions:
                    matched[f"{position}:{ref}"] += 1
                per_pass.setdefault(ref, []).append(absolute_start)
            else:
                heard = str(event.get("heard_text", "")).strip() or "[no heard text]"
                findings.append(f"unmatched/uncertain event near {absolute_start:.1f}s: {heard}")
                unmatched_evidence.append({"absolute_start": absolute_start, "heard_text": heard, "kind": event.get("kind"), "note": event.get("note"), "chunk": item["chunk"]["index"], "pass": item["pass_index"]})
            if event.get("kind") != "instrumental" and absolute_start + 0.2 < last_start:
                findings.append("non-monotonic vocal report; resolve chunk overlap before applying timings")
            last_start = max(last_start, absolute_start)
    for ref, count in matched.items():
        if count == 0:
            findings.append(f"sequence entry never matched by any pass: {ref}")
    for ref, starts in per_pass.items():
        if len(starts) >= 2 and max(starts) - min(starts) > 1.5:
            findings.append(f"timing disagreement over 1.5s for {ref}: {min(starts):.1f}s–{max(starts):.1f}s")
    if not reports:
        findings.append("no model reports were produced")
    return {
        "duration_seconds": duration,
        "expected_sequence": sequence,
        "matched_event_counts": matched,
        "unmatched_evidence": unmatched_evidence,
        "review_required": True,
        "publish_blocked": bool(findings),
        "findings": findings,
        "instruction": "Do not edit SONG_SEQUENCE or SONG_TIMINGS until every finding is resolved against the audio. Timestamp each displayed entry at its first audible vocal onset.",
    }


def main() -> int:
    args = parse_args()
    if args.passes < 1 or args.chunk_seconds <= 0 or args.overlap_seconds < 0:
        raise SystemExit("passes must be positive; chunk seconds positive; overlap non-negative")
    song_dir = args.song_dir.resolve()
    audio = (args.audio or song_dir / "audio.m4a").resolve()
    requested_data = args.data or song_dir / "data.js"
    data = requested_data.resolve() if requested_data.is_file() else None
    output_dir = (args.output_dir or song_dir / ".transcription").resolve()
    if not audio.is_file():
        raise SystemExit("song directory must contain audio.m4a (or pass --audio)")
    api_key = read_api_key(args.key_file)
    lines, sequence = parse_song_data(data)
    duration = probe_duration(audio)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    audio_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="bhakti-audio-") as temporary:
        chunks = create_chunks(audio, duration, args.chunk_seconds, args.overlap_seconds, Path(temporary))
        for chunk in chunks:
            for pass_index in range(1, args.passes + 1):
                print(f"Analyzing chunk {chunk.index + 1}/{len(chunks)}, pass {pass_index}/{args.passes}…", file=sys.stderr)
                response = send_request(api_key, args.model, chunk.path, prompt_for(chunk, lines, sequence), args.timeout)
                artifact = {
                    "created_at_epoch": time.time(),
                    "audio_sha256": audio_hash,
                    "source_audio": str(audio),
                    "model_requested": args.model,
                    "chunk": {key: value for key, value in asdict(chunk).items() if key != "path"},
                    "pass_index": pass_index,
                    "response": response,
                }
                artifact_path = output_dir / f"chunk-{chunk.index:03d}-pass-{pass_index}.json"
                artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                reports.append(artifact)
    review = review_reports(reports, duration, sequence)
    (output_dir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(reports)} review artifacts to {output_dir}", file=sys.stderr)
    print(f"Publish blocked: {review['publish_blocked']}; findings: {len(review['findings'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
