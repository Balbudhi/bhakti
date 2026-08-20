#!/usr/bin/env python3
"""Build reviewed Bhakti readers from local audio or YouTube URLs.

This is the production intake command.  It deliberately separates the model
jobs which were previously interleaved in ad-hoc song work:

  1. complete transcription, 2. transcript-aware audit, 3. lyric-aware timing,
  4. word glosses, 5. literal translation derived only from those glosses,
  6. deterministic reader/catalogue generation.

The command accepts ``--song slug=SOURCE`` repeatedly or a JSON batch manifest
and can run independent songs concurrently.  It never commits or pushes: that
remains a path-scoped repository action after the generated output is checked.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

import process_song_gemini as gemini
import naming


ROOT = Path(__file__).resolve().parents[1]
MODEL = gemini.MODEL
LONG_MERGE_VERSION = 2
GLOSS_CONTRACT_VERSION = 2
TRANSLATION_INPUT_VERSION = 6
SEMANTIC_FRAME_FIELDS = (
    "agent", "action_or_state", "patient_or_complement", "modifiers",
    "negation_or_modality", "literal_image_and_agency", "idiom_or_phrase",
    "cross_line_relation",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--song", action="append", default=[], metavar="SLUG=SOURCE",
                        help="Local audio path or yt-dlp URL. Repeat for a batch.")
    parser.add_argument("--url", action="append", default=[],
                        help="YouTube/media URL with automatic slug, title, and description-credit extraction. Repeat for a batch.")
    parser.add_argument("--batch", type=Path,
                        help="JSON: {songs:[{slug, source, title?, writer?, singer?, composer?, languages?, subjectTags?, searchAliases?}]}")
    parser.add_argument("--workers", type=int, default=1,
                        help="Independent songs to process concurrently (default: 1).")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--publish", action="store_true",
                        help="Generate readers and update data/songs.js after all required checks pass.")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--force", action="store_true", help="Rerun cached API stages for an existing intake.")
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_packet(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def is_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def embedded_audio_metadata(path: Path) -> dict[str, Any]:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=title,artist,album,composer,genre,date,track",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True)
    tags = json.loads(result.stdout).get("format", {}).get("tags", {})
    return {str(key).casefold(): value for key, value in tags.items() if value not in (None, "")}


def normalise_jobs(options: argparse.Namespace) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for spec in options.song:
        if "=" not in spec:
            raise SystemExit("--song must be SLUG=SOURCE")
        slug, source = spec.split("=", 1)
        jobs.append({"slug": slug.strip(), "source": source.strip()})
    for url in getattr(options, "url", []):
        metadata = json.loads(subprocess.run(
            ["yt-dlp", "--no-playlist", "--dump-single-json", "--skip-download", url],
            check=True, capture_output=True, text=True,
        ).stdout)
        fields: dict[str, str] = {}
        for line in str(metadata.get("description") or "").splitlines():
            match = re.match(r"\s*([^:]{2,30})\s*:\s*(.+?)\s*$", line)
            if match:
                fields[match.group(1).strip().casefold()] = match.group(2).strip()
        raw_title = str(metadata.get("title") or metadata.get("id") or "song")
        title = fields.get("song") or re.sub(r"\s+with lyrics\b.*$", "", raw_title.split("|")[0], flags=re.I).strip()
        jobs.append({"slug": naming.slugify(title), "source": metadata.get("webpage_url") or url,
                     "title": title, "subtitle": fields.get("album", ""),
                     "writer": fields.get("lyricist", ""),
                     "singer": fields.get("artist") or fields.get("singer", ""),
                     "composer": fields.get("music director") or fields.get("composer", ""),
                     "searchAliases": [raw_title], "_source_metadata": metadata})
    if options.batch:
        raw = json.loads(options.batch.read_text(encoding="utf-8"))
        entries = raw.get("songs", []) if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            raise SystemExit("batch must be a JSON list or an object with a songs list")
        jobs.extend(entries)
    if not jobs:
        raise SystemExit("provide --song SLUG=SOURCE or --batch manifest.json")
    seen: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("slug"), str) or not isinstance(job.get("source"), str):
            raise SystemExit("each job needs string slug and source")
        aliases = job.get("searchAliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise SystemExit(f"searchAliases for {job['slug']!r} must be a list of strings")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", job["slug"]):
            raise SystemExit(f"invalid slug: {job['slug']!r}")
        if job["slug"] in seen:
            raise SystemExit(f"duplicate slug: {job['slug']}")
        seen.add(job["slug"])
    return jobs


def intake(job: dict[str, Any], *, force: bool) -> tuple[Path, dict[str, Any]]:
    song_dir = ROOT / "songs" / job["slug"]
    audio = song_dir / "audio.m4a"
    if song_dir.exists() and any(song_dir.iterdir()):
        if audio.is_file():
            return song_dir, read_packet(song_dir / ".transcription" / "source.json") or {}
        raise RuntimeError(f"refusing to overwrite non-empty {song_dir}")
    song_dir.mkdir(parents=True, exist_ok=True)
    review_dir = song_dir / ".transcription"
    review_dir.mkdir(exist_ok=True)
    source_value = job["source"]
    if is_url(source_value):
        metadata = job.get("_source_metadata") or json.loads(subprocess.run(
            ["yt-dlp", "--no-playlist", "--dump-single-json", "--skip-download", source_value],
            check=True, capture_output=True, text=True,
        ).stdout)
        source = {
            "source_url": metadata.get("webpage_url") or source_value,
            "title": metadata.get("title"), "uploader": metadata.get("uploader"),
            "channel": metadata.get("channel"), "upload_date": metadata.get("upload_date"),
            "duration_seconds": metadata.get("duration"), "description": metadata.get("description"),
            "extractor_key": metadata.get("extractor_key"), "id": metadata.get("id"),
            "review_note": "Source metadata is evidence to verify, never automatic public credit.",
        }
        subprocess.run(["yt-dlp", "--no-playlist", "-f", "bestaudio", "-o", str(song_dir / "audio.%(ext)s"), source_value], check=True)
        originals = [path for path in song_dir.glob("audio.*") if path.suffix not in {".part", ".ytdl"}]
        if len(originals) != 1:
            raise RuntimeError(f"expected one best-audio download from {source_value}, found {len(originals)}")
        primary = originals[0]
        if primary.suffix.casefold() != ".m4a":
            try:
                subprocess.run(["yt-dlp", "--no-playlist", "-f", "bestaudio[ext=m4a]", "-o", str(audio), source_value], check=True)
            except subprocess.CalledProcessError:
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(primary),
                                "-vn", "-c:a", "aac", "-b:a", "192k", str(audio)], check=True)
    else:
        supplied = Path(source_value).expanduser().resolve()
        if not supplied.is_file():
            raise RuntimeError(f"audio source does not exist: {supplied}")
        if supplied.suffix.casefold() == ".m4a":
            shutil.copy2(supplied, audio)
        else:
            preserved = song_dir / f"audio{supplied.suffix.casefold()}"
            shutil.copy2(supplied, preserved)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(supplied),
                            "-vn", "-c:a", "aac", "-b:a", "192k", str(audio)], check=True)
        tags = embedded_audio_metadata(supplied)
        source = {"source_file": supplied.name, "title": tags.get("title") or supplied.stem,
                  "artist": tags.get("artist"), "album": tags.get("album"),
                  "composer": tags.get("composer"), "genre": tags.get("genre"),
                  "review_note": "Local file metadata is evidence to verify, never automatic public credit."}
    write_json(review_dir / "source.json", source)
    return song_dir, source


def listener_audio_sources(song_dir: Path) -> list[dict[str, str]]:
    types = {".webm": "audio/webm; codecs=opus", ".ogg": "audio/ogg; codecs=opus",
             ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".m4a": "audio/mp4"}
    preferred = [".webm", ".ogg", ".flac", ".wav", ".mp3", ".m4a"]
    return [{"src": f"audio{suffix}", "type": types[suffix]}
            for suffix in preferred if (song_dir / f"audio{suffix}").is_file()]


def preferred_listener_audio(song_dir: Path) -> Path:
    sources = listener_audio_sources(song_dir)
    if not sources:
        raise RuntimeError(f"no listener audio found in {song_dir}")
    return song_dir / sources[0]["src"]


def edge_trim_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "edge": {"type": "string"}, "decision": {"type": "string"}, "boundary": {"type": "number"},
        "outside_type": {"type": "string"}, "confidence": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["edge", "decision", "boundary", "outside_type", "confidence", "reason"],
        "additionalProperties": False}


def detect_youtube_trim(song_dir: Path, source: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "trim-review.json"
    cached = read_packet(target)
    if cached:
        return cached
    audio = preferred_listener_audio(song_dir)
    duration = gemini.duration_seconds(audio)
    edge_length = min(75.0, duration)
    with tempfile.TemporaryDirectory(prefix="bhakti-trim-review-") as temporary:
        destination = Path(temporary)
        jobs = []
        for edge, clip_start in (("start", 0.0), ("end", max(0.0, duration - edge_length))):
            clip = destination / f"{edge}.m4a"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{clip_start:.3f}",
                            "-i", str(audio), "-t", f"{edge_length:.3f}", "-vn", "-c:a", "aac", "-b:a", "192k",
                            str(clip)], check=True)
            jobs.append((edge, clip_start, clip))

        def run(job: tuple[str, float, Path]) -> dict[str, Any]:
            edge, clip_start, clip = job
            prompt = f"""Classify the {edge} edge of a YouTube-sourced song. This clip covers absolute source seconds {clip_start:.3f}–{clip_start + edge_length:.3f}.

Crop only definite non-song platform material: spoken channel promotion, logo sting, advertisement, countdown, unrelated narration, or post-song promotional speech. Preserve every musical introduction, instrumental prelude, devotional invocation, wordless vocal, intentional silence, final sung note, and natural fade.

For the start edge, boundary is the relative second where the actual song recording begins. For the end edge, boundary is the relative second through which the actual song/fade must be kept. If no crop is justified, decision must be keep and boundary must be 0 for start or {edge_length:.3f} for end. Use trim only with high confidence.

Return strict JSON only."""
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                   response_schema=edge_trim_schema(), schema_name=f"bhakti_{edge}_trim",
                                   reasoning_effort="high", max_completion_tokens=4096)
            return {"edge": edge, "clip_start": clip_start, "response": response}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, jobs))
    by_edge = {item["edge"]: item for item in results}
    allowed = {"platform_spoken", "promotion", "advertisement", "logo_sting", "countdown", "unrelated_narration"}
    start_packet = by_edge["start"]["response"]["packet"]
    end_packet = by_edge["end"]["response"]["packet"]
    trim_start = (float(start_packet["boundary"]) if start_packet.get("decision") == "trim"
                  and str(start_packet.get("confidence", "")).casefold() == "high"
                  and str(start_packet.get("outside_type", "")).casefold() in allowed else 0.0)
    relative_end = (float(end_packet["boundary"]) if end_packet.get("decision") == "trim"
                    and str(end_packet.get("confidence", "")).casefold() == "high"
                    and str(end_packet.get("outside_type", "")).casefold() in allowed else edge_length)
    trim_end = by_edge["end"]["clip_start"] + relative_end
    errors = []
    if not 0 <= trim_start < trim_end <= duration or duration - (trim_end - trim_start) > min(120.0, duration * 0.2):
        errors.append("proposed edge trim is outside safety bounds")
    artifact = {"duration": duration, "start": by_edge["start"], "end": by_edge["end"],
                "trim_start": round(trim_start, 3), "trim_end": round(trim_end, 3),
                "validation_errors": errors, "status": "blocked" if errors else "reviewed"}
    write_json(target, artifact)
    return artifact


def apply_lossless_trim(song_dir: Path, artifact: dict[str, Any]) -> None:
    marker = song_dir / ".transcription" / "trim-applied.json"
    if marker.is_file():
        return
    if artifact.get("validation_errors"):
        raise RuntimeError("cannot apply blocked trim review")
    start, end, duration = float(artifact["trim_start"]), float(artifact["trim_end"]), float(artifact["duration"])
    if start <= 0.001 and end >= duration - 0.001:
        write_json(marker, {"applied": False, "reason": "no non-song edge material"})
        return
    for source in listener_audio_sources(song_dir):
        path = song_dir / source["src"]
        temporary = path.with_name(f"{path.stem}.trimmed{path.suffix}")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ss", f"{start:.3f}",
                        "-to", f"{end:.3f}", "-map", "0:a:0", "-c", "copy", "-avoid_negative_ts", "make_zero",
                        str(temporary)], check=True)
        if gemini.duration_seconds(temporary) <= 0:
            raise RuntimeError(f"trim produced empty audio: {path}")
        temporary.replace(path)
    write_json(marker, {"applied": True, "trim_start": start, "trim_end": end,
                        "removed_seconds": round(duration - (end - start), 3)})


def ask(prompt: str, audio: Path | None, options: argparse.Namespace) -> dict[str, Any]:
    return gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=options.timeout)


def canonical_timing_audio(source: Path, destination: Path) -> Path:
    """Create a metadata-free fixed-rate API copy without changing song time."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-map_metadata", "-1",
                    "-vn", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(destination)], check=True)
    source_duration = gemini.duration_seconds(source)
    normalized_duration = gemini.duration_seconds(destination)
    if abs(source_duration - normalized_duration) > 0.1:
        raise RuntimeError(f"canonical timing audio changed duration by {normalized_duration - source_duration:.3f}s")
    return destination


def rms_frames(audio: Path, frame_seconds: float = 0.5) -> list[tuple[float, float]]:
    samples = round(44100 * frame_seconds)
    command = ["ffmpeg", "-v", "error", "-i", str(audio), "-af",
               f"aresample=44100,aformat=channel_layouts=mono,asetnsamples=n={samples}:p=0,"
               "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
               "-f", "null", "-"]
    output = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    points: list[tuple[float, float]] = []
    current_time: float | None = None
    for line in output.splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if match:
            current_time = float(match.group(1))
            continue
        match = re.search(r"RMS_level=(-?(?:[0-9.]+|inf))", line)
        if match and current_time is not None:
            level = -120.0 if match.group(1) == "-inf" else float(match.group(1))
            points.append((current_time, level))
    if not points:
        raise RuntimeError("FFmpeg did not produce RMS frames for adaptive segmentation")
    return points


def adaptive_audio_segments(
    audio: Path, *, target_seconds: float = 300.0, search_radius: float = 75.0,
    overlap: float = 15.0, minimum_core: float = 180.0,
) -> list[dict[str, float | int]]:
    duration = gemini.duration_seconds(audio)
    points = rms_frames(audio)
    boundaries = [0.0]
    target = target_seconds
    while target < duration - minimum_core:
        candidates = [(time, level) for time, level in points
                      if max(boundaries[-1] + minimum_core, target - search_radius) <= time <= min(duration - minimum_core, target + search_radius)]
        if not candidates:
            boundary = min(duration - minimum_core, max(boundaries[-1] + minimum_core, target))
        else:
            boundary = min(candidates, key=lambda item: (item[1], abs(item[0] - target)))[0] + 0.25
        boundaries.append(round(boundary, 3))
        target = boundary + target_seconds
    boundaries.append(duration)
    return [{"index": index, "core_start": boundaries[index], "core_end": boundaries[index + 1],
             "clip_start": max(0.0, boundaries[index] - overlap),
             "clip_end": min(duration, boundaries[index + 1] + overlap)}
            for index in range(len(boundaries) - 1)]


def segment_transcript_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "source_text": {"type": "string"}, "roman": {"type": "string"},
            "language": {"type": "string"}, "kind": {"type": "string"}, "partial": {"type": "string"},
            "notes": {"type": "string"}},
            "required": ["id", "source_text", "roman", "language", "kind", "partial", "notes"],
            "additionalProperties": False}},
        "performance_order": {"type": "array", "items": {"type": "object", "properties": {
            "line_id": {"type": "string"}, "occurrence": {"type": "integer"}},
            "required": ["line_id", "occurrence"], "additionalProperties": False}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    }, "required": ["lines", "performance_order", "uncertainties"], "additionalProperties": False}


def transcribe_long_audio(
    song_dir: Path, source: dict[str, Any], audio: Path, options: argparse.Namespace
) -> dict[str, Any]:
    segments = adaptive_audio_segments(audio)
    with tempfile.TemporaryDirectory(prefix="bhakti-long-transcript-") as temporary:
        destination = Path(temporary)
        jobs = []
        for segment in segments:
            clip = destination / f"segment-{segment['index']:03d}.m4a"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{segment['clip_start']:.3f}",
                            "-i", str(audio), "-t", f"{segment['clip_end'] - segment['clip_start']:.3f}", "-vn",
                            "-c:a", "aac", "-b:a", "192k", str(clip)], check=True)
            jobs.append((segment, clip))

        def run(job: tuple[dict[str, Any], Path]) -> dict[str, Any]:
            segment, clip = job
            prompt = f"""Transcribe this complete devotional-song excerpt with extreme care. Listen through the entire clip repeatedly enough to avoid missing a single sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Do not translate. Do not infer unheard text. Mark uncertainty rather than guessing.

This is segment {segment['index']} of a longer recording. Its audio covers absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; its non-overlap core is {segment['core_start']:.3f}–{segment['core_end']:.3f}. Text in the overlap is intentionally duplicated and must still be transcribed. Identify the language and native script per line, including code-switching.

Source metadata is only a lead, never proof:
{json.dumps(source, ensure_ascii=False)}

Return strict JSON:
{{"lines":[{{"id":"segment-{segment['index']}-line-000","source_text":"","roman":"","language":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","partial":"none|leading|trailing","notes":""}}],"performance_order":[{{"line_id":"","occurrence":1}}],"uncertainties":[]}}"""
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                   response_schema=segment_transcript_schema(), schema_name="bhakti_segment_transcript",
                                   reasoning_effort="high", max_completion_tokens=32768)
            return {"segment": segment, "response": response}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            responses = list(pool.map(run, jobs))
    packet = {"segmented": True, "segments": [{"segment": item["segment"], "transcript": item["response"]["packet"]}
                                                for item in responses],
              "instruction": "Overlaps are duplicate evidence. The full-audio audit must reconcile them into one exact performance order."}
    return {"packet": packet, "segment_responses": responses, "resolved_model": options.model}


def transcript(song_dir: Path, source: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "01-transcript.json"
    existing = read_packet(target)
    if existing and not options.force:
        return existing
    if gemini.duration_seconds(audio) > 900:
        result = transcribe_long_audio(song_dir, source, audio, options)
        write_json(target, result)
        return result
    prompt = f"""Transcribe this complete devotional recording exactly. Listen from beginning to end.

Do not translate. Do not omit any sung, spoken, call-and-response, invocation, refrain, pickup, return, or closing line. Do not infer repetition counts: list every performance occurrence in order. Use the appropriate source script whenever known and careful romanization. Unknown words or credits must be marked uncertain rather than invented.

Source metadata is only a lead, not proof of public credits:
{json.dumps(source, ensure_ascii=False)}

Return strict JSON:
{{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"lines":[{{"id":"stable-kebab-id","source_text":"","roman":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"stable-kebab-id","occurrence":1,"notes":""}}],"uncertainties":[]}}"""
    result = ask(prompt, audio, options)
    write_json(target, result)
    return result


def audited_transcript_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "metadata": {"type": "object", "properties": {
            "languages": {"type": "array", "items": {"type": "string"}}, "script": {"type": "string"},
            "singer_candidates": {"type": "array", "items": {"type": "string"}},
            "credit_evidence": {"type": "array", "items": {"type": "string"}}},
            "required": ["languages", "script", "singer_candidates", "credit_evidence"], "additionalProperties": False},
        "verified_lines": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "source_text": {"type": "string"}, "roman": {"type": "string"},
            "kind": {"type": "string"}, "translation_notes": {"type": "string"}},
            "required": ["id", "source_text", "roman", "kind", "translation_notes"], "additionalProperties": False}},
        "performance_order": {"type": "array", "items": {"type": "object", "properties": {
            "line_id": {"type": "string"}, "occurrence": {"type": "integer"}, "notes": {"type": "string"}},
            "required": ["line_id", "occurrence", "notes"], "additionalProperties": False}},
        "changes": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    }, "required": ["metadata", "verified_lines", "performance_order", "changes", "uncertainties"],
        "additionalProperties": False}


def lyric_signature(line: dict[str, Any]) -> str:
    value = str(line.get("source_text") or line.get("roman") or "").casefold()
    value = unicodedata.normalize("NFKD", value)
    return "".join(character for character in value if character.isalnum() and not unicodedata.combining(character))


def ordered_segment_lines(packet: dict[str, Any]) -> list[dict[str, Any]]:
    lines = {line["id"]: line for line in packet.get("lines", [])}
    return [lines[entry["line_id"]] for entry in packet.get("performance_order", []) if entry.get("line_id") in lines]


def balanced_overlap(left: list[dict[str, Any]], right: list[dict[str, Any]], limit: int = 20) -> tuple[int, int, float]:
    best = (0, 0, 0.0)
    for left_count in range(1, min(limit, len(left)) + 1):
        left_text = "".join(lyric_signature(line) for line in left[-left_count:])
        for right_count in range(1, min(limit, len(right)) + 1):
            right_text = "".join(lyric_signature(line) for line in right[:right_count])
            if min(len(left_text), len(right_text)) < 15:
                continue
            similarity = difflib.SequenceMatcher(None, left_text, right_text).ratio()
            balance = min(len(left_text), len(right_text)) / max(len(left_text), len(right_text))
            score = similarity * balance
            if score > best[2]:
                best = (left_count, right_count, score)
    return best


def normalized_language(value: str) -> str:
    key = value.strip().casefold()
    return {"hi": "Hindi", "hin": "Hindi", "hindi": "Hindi", "mr": "Marathi", "mar": "Marathi",
            "marathi": "Marathi", "sa": "Sanskrit", "san": "Sanskrit", "sanskrit": "Sanskrit",
            "pa": "Punjabi", "pan": "Punjabi", "punjabi": "Punjabi", "kn": "Kannada", "kan": "Kannada",
            "kannada": "Kannada"}.get(key, value.strip())


def merge_audited_segments(audited_segments: list[dict[str, Any]]) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    seam_matches: list[dict[str, int]] = []
    languages: list[str] = []
    uncertainties: list[str] = []
    for index, item in enumerate(audited_segments):
        packet = item["audit"]["packet"]
        current = ordered_segment_lines(packet)
        # Overlap lets the adjoining segment carry the complete line. Internal
        # leading/trailing fragments are evidence, not separate performances.
        if index > 0:
            current = [line for line in current if line.get("partial") != "leading"]
        if index + 1 < len(audited_segments):
            current = [line for line in current if line.get("partial") != "trailing"]
        for line in packet.get("lines", []):
            language = normalized_language(str(line.get("language", "")))
            if language and language not in languages:
                languages.append(language)
        uncertainties.extend(str(value) for value in packet.get("uncertainties", []))
        overlap = 0
        left_overlap = 0
        score = 1.0
        if merged:
            left_overlap, overlap, score = balanced_overlap(merged, current)
            if score < 0.8:
                uncertainties.append(f"segment seam {index - 1}/{index} overlap score is only {score:.3f}")
        seam_matches.append({"left_segment": max(0, index - 1), "right_segment": index,
                             "left_overlap_occurrences": left_overlap,
                             "right_overlap_occurrences": overlap, "score": round(score, 3)})
        merged.extend(current[overlap:])
    canonical: dict[str, dict[str, Any]] = {}
    order: list[dict[str, Any]] = []
    occurrence_counts: dict[str, int] = {}
    for line in merged:
        signature = lyric_signature(line)
        if signature not in canonical:
            line_id = f"line-{len(canonical):03d}"
            canonical[signature] = {"id": line_id, "source_text": line.get("source_text", ""),
                                    "roman": line.get("roman", ""), "kind": line.get("kind", "verse"),
                                    "translation_notes": line.get("notes", "")}
        line_id = canonical[signature]["id"]
        occurrence_counts[line_id] = occurrence_counts.get(line_id, 0) + 1
        order.append({"line_id": line_id, "occurrence": occurrence_counts[line_id], "notes": ""})
    return {"metadata": {"languages": languages, "script": "mixed" if len(languages) > 1 else (languages[0] if languages else ""),
                         "singer_candidates": [], "credit_evidence": []},
            "verified_lines": list(canonical.values()), "performance_order": order,
            "changes": [f"deterministically merged {len(audited_segments)} audited segments",
                        json.dumps(seam_matches, separators=(",", ":"))],
            "uncertainties": uncertainties}


def audit_long_transcript(
    song_dir: Path, raw: dict[str, Any], audio: Path, options: argparse.Namespace
) -> dict[str, Any]:
    segments = raw["packet"]["segments"]
    cache_dir = song_dir / ".transcription" / "pipeline" / "audit-segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-long-audit-") as temporary:
        destination = Path(temporary)
        jobs = []
        for item in segments:
            segment = item["segment"]
            clip = destination / f"segment-{segment['index']:03d}.m4a"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{segment['clip_start']:.3f}",
                            "-i", str(audio), "-t", f"{segment['clip_end'] - segment['clip_start']:.3f}", "-vn",
                            "-c:a", "aac", "-b:a", "192k", str(clip)], check=True)
            jobs.append((item, clip))

        def run(job: tuple[dict[str, Any], Path]) -> dict[str, Any]:
            item, clip = job
            segment, first = item["segment"], item["transcript"]
            cached_path = cache_dir / f"segment-{segment['index']:03d}.json"
            cached = read_packet(cached_path)
            if cached:
                return cached
            prompt = f"""This is the required second transcription pass for one segment of a long devotional recording. Audit the entire first-pass transcript below against the complete attached segment. Use the first transcript as your working draft; do not start over.

Be extremely careful not to miss, hallucinate, reorder, or silently correct any sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Preserve overlap text because local code reconciles it. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation. Do not translate or estimate timestamps. Mark genuine uncertainty rather than guessing.

Segment audio: absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; core {segment['core_start']:.3f}–{segment['core_end']:.3f}.

FIRST TRANSCRIPT:
{json.dumps(first, ensure_ascii=False)}

Return strict JSON:
{{"lines":[{{"id":"segment-{segment['index']}-line-000","source_text":"","roman":"","language":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","partial":"none|leading|trailing","notes":""}}],"performance_order":[{{"line_id":"","occurrence":1}}],"uncertainties":[]}}"""
            last_error: RuntimeError | None = None
            for attempt in range(3):
                try:
                    response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                           response_schema=segment_transcript_schema(), schema_name="bhakti_segment_audit",
                                           reasoning_effort="high", max_completion_tokens=32768)
                    result = {"segment": segment, "first": first, "audit": response}
                    write_json(cached_path, result)
                    return result
                except RuntimeError as exc:
                    last_error = exc
                    if "HTTP 502" not in str(exc) or attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            raise last_error or RuntimeError("segment audit failed")

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            audited_segments = list(pool.map(run, jobs))
    merged = merge_audited_segments(audited_segments)
    return {"packet": merged, "segment_audits": audited_segments,
            "merge_contract_version": LONG_MERGE_VERSION, "resolved_model": options.model}


def audit_transcript(song_dir: Path, raw: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "02-transcript-audit.json"
    existing = read_packet(target)
    if existing and not options.force:
        if existing.get("segment_audits") and existing.get("merge_contract_version") != LONG_MERGE_VERSION:
            existing["packet"] = merge_audited_segments(existing["segment_audits"])
            existing["merge_contract_version"] = LONG_MERGE_VERSION
            write_json(target, existing)
        return existing
    if raw.get("packet", {}).get("segmented"):
        result = audit_long_transcript(song_dir, raw, audio, options)
        write_json(target, result)
        return result
    prompt = f"""This is the required second transcription pass. Audit the entire first-pass transcript below against the complete attached devotional recording from beginning to end. Use the first transcript as your explicit working draft; do not start from an empty guess. This is transcription verification, not timing or translation.

Be extremely careful: correct every missed, hallucinated, duplicated, reordered, or misheard lyric. Preserve every audible performance occurrence in exact order, including lead pickups before answers and later returns. When the draft came from overlapping segments, reconcile duplicate overlap evidence without deleting genuine repeated performances. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation; do not mix plain and scholarly spellings. Do not translate or estimate timestamps. If any content remains unclear, put it in uncertainties; do not silently guess.

Candidate transcript:
{json.dumps(raw['packet'], ensure_ascii=False)}

Return strict JSON:
{{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"verified_lines":[{{"id":"stable-kebab-id","source_text":"","roman":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"stable-kebab-id","occurrence":1,"notes":""}}],"changes":[],"uncertainties":[]}}"""
    result = gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=options.timeout,
                         response_schema=audited_transcript_schema(), schema_name="bhakti_audited_transcript",
                         reasoning_effort="high", max_completion_tokens=65536)
    write_json(target, result)
    return result


def display_occurrences(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Compress only immediately contiguous identical audited occurrences."""
    lines = {line["id"]: line for line in packet.get("verified_lines", [])}
    blocks: list[dict[str, Any]] = []
    for raw in packet.get("performance_order", []):
        ref = raw.get("line_id")
        if ref not in lines:
            raise RuntimeError(f"performance order uses unknown line {ref!r}")
        if blocks and blocks[-1]["ref"] == ref:
            blocks[-1]["repeats"] += 1
            continue
        line = lines[ref]
        blocks.append({"occurrence_id": f"occ-{len(blocks):03d}", "ref": ref, "repeats": 1,
                       "source_text": line.get("source_text", ""), "roman": line.get("roman", ""),
                       "section": line.get("kind", "verse")})
    return blocks


def long_coarse_sequence(
    audited: dict[str, Any], occurrences: list[dict[str, Any]], duration: float
) -> list[dict[str, Any]]:
    merged: list[tuple[dict[str, Any], float, int]] = []
    segment_audits = audited.get("segment_audits", [])
    for position, item in enumerate(segment_audits):
        segment = item["segment"]
        current = ordered_segment_lines(item["audit"]["packet"])
        if position > 0:
            current = [line for line in current if line.get("partial") != "leading"]
        if position + 1 < len(segment_audits):
            current = [line for line in current if line.get("partial") != "trailing"]
        span = float(segment["clip_end"]) - float(segment["clip_start"])
        timed = [(line, float(segment["clip_start"]) + span * index / max(1, len(current)), int(segment["index"]))
                 for index, line in enumerate(current)]
        overlap = balanced_overlap([line for line, _, _ in merged], current)[1] if merged else 0
        merged.extend(timed[overlap:])
    compressed: list[tuple[float, int]] = []
    previous_signature = None
    for line, point, segment_index in merged:
        signature = lyric_signature(line)
        if signature == previous_signature:
            continue
        compressed.append((point, segment_index))
        previous_signature = signature
    if len(compressed) != len(occurrences):
        raise RuntimeError(f"long-audio coarse hints differ from display occurrences ({len(compressed)} vs {len(occurrences)})")
    starts: list[float] = []
    for point, _ in compressed:
        starts.append(round(min(duration, max(point, starts[-1] + 0.1 if starts else 0.0)), 3))
    return [{"occurrence_id": occurrence["occurrence_id"], "ref": occurrence["ref"],
             "section": occurrence["section"], "repeats": occurrence["repeats"], "start": starts[index],
             "end": starts[index + 1] if index + 1 < len(starts) else duration,
             "segment_index": compressed[index][1]}
            for index, occurrence in enumerate(occurrences)]


def timing_sequence_from_response(
    occurrences: list[dict[str, Any]], response_packet: dict[str, Any], duration: float
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Validate model starts and derive all intervals deterministically."""
    raw_starts = response_packet.get("starts", [])
    expected_ids = [entry["occurrence_id"] for entry in occurrences]
    observed_ids = [entry.get("occurrence_id") for entry in raw_starts]
    errors: list[str] = []
    if observed_ids != expected_ids:
        errors.append(f"returned occurrence order differs from the audited order: expected {expected_ids}, got {observed_ids}")
    starts: list[float] = []
    for index, raw in enumerate(raw_starts):
        try:
            point = float(raw["start"])
            if not 0 <= point <= duration or (starts and point <= starts[-1]):
                raise ValueError
            starts.append(point)
        except (KeyError, TypeError, ValueError):
            errors.append(f"start[{index}] is missing, out of range, or non-increasing")
    uncertain_raw = response_packet.get("uncertain_occurrence_ids", [])
    uncertain = [str(item) for item in uncertain_raw if isinstance(item, str) and item.strip()]
    sequence: list[dict[str, Any]] = []
    if len(starts) == len(occurrences):
        for index, occurrence in enumerate(occurrences):
            sequence.append({"occurrence_id": occurrence["occurrence_id"], "ref": occurrence["ref"],
                             "section": occurrence["section"], "repeats": occurrence["repeats"],
                             "start": round(starts[index], 3),
                             "end": round(starts[index + 1] if index + 1 < len(starts) else duration, 3)})
    return sequence, errors, uncertain


def start_only_timing_prompt(occurrences: list[dict[str, Any]], duration: float) -> str:
    return f"""The attached audio is one complete devotional recording, exactly {duration:.3f} seconds long. Its lyrics and performance order below are already fully transcribed and audited. Do not transcribe, correct, identify, reorder, group, or explain anything.

Your only task is to return the absolute source-recording second at which the FIRST AUDIBLE SYLLABLE of each listed display occurrence begins. The repeats value is already final and means immediately contiguous identical performances; timestamp the first syllable of its first repetition. Musical introductions and interludes remain unassigned. Listen carefully from start to finish. Never use the middle of a line, a later chorus, or a response as its start.

Final ordered display occurrences:
{json.dumps(occurrences, ensure_ascii=False)}

Return strict JSON only, with every occurrence exactly once and in the supplied order:
{{"starts":[{{"occurrence_id":"occ-000","start":0.0}}],"uncertain_occurrence_ids":[]}}"""


def start_only_timing_schema(count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "starts": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {"occurrence_id": {"type": "string"}, "start": {"type": "number"}},
                    "required": ["occurrence_id", "start"],
                    "additionalProperties": False,
                },
            },
            "uncertain_occurrence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["starts", "uncertain_occurrence_ids"],
        "additionalProperties": False,
    }


def build_timing_chunks(
    occurrences: list[dict[str, Any]], coarse_sequence: list[dict[str, Any]], duration: float,
    *, width: float = 120.0, overlap: float = 15.0,
) -> list[dict[str, Any]]:
    """Build one bounded verification grid after the full-song coarse pass."""
    primary = []
    start = 0.0
    while start < duration:
        primary.append((start, min(duration, start + width)))
        start += width

    chunks: list[dict[str, Any]] = []
    for core_start, core_end in primary:
        indices = [index for index, entry in enumerate(coarse_sequence)
                   if core_start <= entry["start"] < core_end
                   or (core_end == duration and entry["start"] == duration)]
        if not indices:
            continue
        first, last = indices[0], indices[-1]
        chunks.append({"index": len(chunks), "grid": "verification",
                       "core_start": core_start, "core_end": core_end,
                       "clip_start": max(0.0, core_start - overlap),
                       "clip_end": min(duration, core_end + overlap),
                       "target_indices": indices,
                       "target_occurrences": [{**occurrences[index], "coarse_source_start": coarse_sequence[index]["start"]}
                                              for index in indices],
                       "preceding_context": occurrences[first - 1] if first else None,
                       "following_context": occurrences[last + 1] if last + 1 < len(occurrences) else None})
    return chunks

def chunk_start_schema(count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "starts": {"type": "array", "minItems": count, "maxItems": count, "items": {
                "type": "object",
                "properties": {"occurrence_id": {"type": "string"}, "start": {"type": "number"}},
                "required": ["occurrence_id", "start"], "additionalProperties": False}},
            "uncertain_occurrence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["starts", "uncertain_occurrence_ids"],
        "additionalProperties": False,
    }


def refine_timing_chunk(
    audio: Path, occurrences: list[dict[str, Any]], chunk: dict[str, Any],
    options: argparse.Namespace, destination: Path, cache_path: Path | None = None,
    *, max_coarse_delta: float = 20.0, reasoning_effort: str = "high",
    max_completion_tokens: int | None = None,
) -> dict[str, Any]:
    targets = chunk["target_occurrences"]
    cache_key = {
        "model": options.model,
        "reasoning_effort": reasoning_effort,
        "max_coarse_delta": max_coarse_delta,
        "clip_start": chunk["clip_start"],
        "clip_end": chunk["clip_end"],
        "targets": targets,
        "preceding_context": chunk["preceding_context"],
        "following_context": chunk["following_context"],
    }
    if cache_path and not options.force:
        cached = read_packet(cache_path)
        if cached and cached.get("cache_key") == cache_key:
            return cached
    clip = destination / f"timing-{chunk['index']:03d}.m4a"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{chunk['clip_start']:.3f}",
                    "-i", str(audio), "-t", f"{chunk['clip_end'] - chunk['clip_start']:.3f}", "-vn",
                    "-c:a", "aac", "-b:a", "192k", str(clip)], check=True)
    prompt = f"""The lyric transcription, order, repeat grouping, and occurrence IDs below are already final. Do not transcribe, correct, identify, reorder, group, or explain anything.

The attached timing clip is source seconds {chunk['clip_start']:.3f}–{chunk['clip_end']:.3f}. Return times RELATIVE TO THIS CLIP.

PRECEDING CONTEXT ONLY (do not return a time):
{json.dumps(chunk['preceding_context'], ensure_ascii=False) if chunk['preceding_context'] else '(musical introduction / none)'}

TARGET OCCURRENCES IN FINAL ORDER:
{json.dumps(targets, ensure_ascii=False)}

FOLLOWING CONTEXT ONLY (do not return a time):
{json.dumps(chunk['following_context'], ensure_ascii=False) if chunk['following_context'] else '(recording ending / none)'}

Your only task is to return the exact relative second at the FIRST AUDIBLE SYLLABLE of each target occurrence's first repetition. Do not use a line's middle, a response, or a later repetition. Return every target ID exactly once in the supplied order. Mark an ID uncertain rather than guessing.

Return strict JSON only:
{{"starts":[{{"occurrence_id":"{targets[0]['occurrence_id']}","start":0.0}}],"uncertain_occurrence_ids":[]}}"""
    response = None
    last_error: RuntimeError | None = None
    for attempt in range(3):
        try:
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                   response_schema=chunk_start_schema(len(targets)), schema_name="bhakti_chunk_starts",
                                   reasoning_effort=reasoning_effort,
                                   max_completion_tokens=max_completion_tokens or max(32768, len(targets) * 1024))
            break
        except RuntimeError as exc:
            last_error = exc
            if "required JSON packet" not in str(exc) or attempt == 2:
                raise
            time.sleep(2 ** attempt)
    if response is None:
        raise last_error or RuntimeError("timing window returned no structured response")
    packet = response["packet"]
    expected_ids = [target["occurrence_id"] for target in targets]
    observed_ids = [entry.get("occurrence_id") for entry in packet.get("starts", [])]
    errors: list[str] = []
    if observed_ids != expected_ids:
        errors.append(f"chunk IDs differ from targets: expected {expected_ids}, got {observed_ids}")
    uncertain = packet.get("uncertain_occurrence_ids", [])
    if uncertain:
        errors.append(f"chunk marked occurrences uncertain: {uncertain}")
    starts: list[dict[str, Any]] = []
    previous = -1.0
    for index, raw in enumerate(packet.get("starts", [])):
        try:
            point = chunk["clip_start"] + float(raw["start"])
            if not chunk["clip_start"] <= point <= chunk["clip_end"] or point <= previous:
                raise ValueError
            if abs(point - float(targets[index]["coarse_source_start"])) > max_coarse_delta:
                raise ValueError
            previous = point
            starts.append({"occurrence_id": raw["occurrence_id"], "start": round(point, 3)})
        except (KeyError, TypeError, ValueError):
            errors.append(f"chunk start[{index}] is invalid, out of clip, or non-increasing")
    report = {**{key: value for key, value in chunk.items()
                 if key not in {"preceding_context", "following_context", "target_occurrences"}},
              "cache_key": cache_key, "targets": expected_ids, "starts": starts, "uncertain_ids": uncertain,
              "response": response, "validation_errors": errors}
    if cache_path:
        write_json(cache_path, report)
    return report


def build_long_timing_chunks(
    audited: dict[str, Any], occurrences: list[dict[str, Any]], coarse_sequence: list[dict[str, Any]], duration: float,
) -> list[dict[str, Any]]:
    """Assign each merged occurrence to one audited long-audio segment."""
    chunks: list[dict[str, Any]] = []
    assigned: set[int] = set()
    segment_audits = audited.get("segment_audits", [])
    for position, item in enumerate(segment_audits):
        segment = item["segment"]
        core_start, core_end = float(segment["core_start"]), float(segment["core_end"])
        indices = [index for index, entry in enumerate(coarse_sequence)
                   if index not in assigned and int(entry.get("segment_index", -1)) == int(segment["index"])]
        if position == len(segment_audits) - 1:
            indices.extend(index for index in range(len(occurrences)) if index not in assigned and index not in indices)
        if not indices:
            continue
        assigned.update(indices)
        first, last = indices[0], indices[-1]
        chunks.append({
            "index": int(segment["index"]),
            "grid": "long-segment",
            "core_start": core_start,
            "core_end": core_end,
            "clip_start": float(segment["clip_start"]),
            "clip_end": min(duration, float(segment["clip_end"])),
            "target_indices": indices,
            "target_occurrences": [{**occurrences[index], "coarse_source_start": coarse_sequence[index]["start"]}
                                   for index in indices],
            "preceding_context": occurrences[first - 1] if first else None,
            "following_context": occurrences[last + 1] if last + 1 < len(occurrences) else None,
        })
    if assigned != set(range(len(occurrences))):
        raise RuntimeError("long timing segments do not cover every audited occurrence")
    return chunks


def align_long_segments(
    song_dir: Path, audio: Path, audited: dict[str, Any], occurrences: list[dict[str, Any]],
    coarse_sequence: list[dict[str, Any]], duration: float, options: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Align long recordings in their audited 4–6 minute segments, once each."""
    chunks = build_long_timing_chunks(audited, occurrences, coarse_sequence, duration)
    cache_dir = song_dir / ".transcription" / "pipeline" / "long-timing-segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-long-timing-") as temporary:
        destination = Path(temporary)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
            reports = list(pool.map(
                lambda chunk: refine_timing_chunk(
                    audio, occurrences, chunk, options, destination,
                    cache_dir / f"segment-{chunk['index']:03d}.json",
                    max_coarse_delta=max(90.0, chunk["clip_end"] - chunk["clip_start"]),
                    reasoning_effort="high", max_completion_tokens=65536,
                ),
                chunks,
            ))
    errors = [f"segment {report['index']}: {error}" for report in reports for error in report["validation_errors"]]
    starts_by_id: dict[str, float] = {}
    for report in reports:
        if report["validation_errors"]:
            continue
        for entry in report["starts"]:
            if entry["occurrence_id"] in starts_by_id:
                errors.append(f"{entry['occurrence_id']}: duplicate long-segment timing")
            starts_by_id[entry["occurrence_id"]] = float(entry["start"])
    starts = [starts_by_id.get(occurrence["occurrence_id"]) for occurrence in occurrences]
    if any(start is None for start in starts):
        errors.append("long-segment timing is missing one or more occurrences")
    elif any(float(starts[index]) <= float(starts[index - 1]) for index in range(1, len(starts))):
        errors.append("long-segment starts are non-increasing")
    sequence: list[dict[str, Any]] = []
    if not errors:
        for index, occurrence in enumerate(occurrences):
            start = float(starts[index])
            end = float(starts[index + 1]) if index + 1 < len(starts) else duration
            sequence.append({"occurrence_id": occurrence["occurrence_id"], "ref": occurrence["ref"],
                             "section": occurrence["section"], "repeats": occurrence["repeats"],
                             "start": start, "end": end})
    return sequence, reports, errors


def single_start_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "occurrence_id": {"type": "string"}, "start": {"type": "number"}, "uncertainty": {"type": "string"}},
        "required": ["occurrence_id", "start", "uncertainty"], "additionalProperties": False}


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def consensus_value(values: list[float], tolerance: float = 0.5) -> float | None:
    clusters = [[other for other in values if abs(other - candidate) <= tolerance] for candidate in values]
    best = max(clusters, key=len, default=[])
    return round(median(best), 3) if len(best) >= 2 else None


def refine_single_start(
    audio: Path, occurrences: list[dict[str, Any]], index: int, candidate: float,
    duration: float, options: argparse.Namespace, destination: Path,
) -> dict[str, Any]:
    target = occurrences[index]
    clip_start, clip_end = max(0.0, candidate - 20.0), min(duration, candidate + 20.0)
    clip = destination / f"single-{target['occurrence_id']}.m4a"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{clip_start:.3f}",
                    "-i", str(audio), "-t", f"{clip_end - clip_start:.3f}", "-vn", "-c:a", "aac", "-b:a", "192k",
                    str(clip)], check=True)
    previous = occurrences[index - 1] if index else None
    following = occurrences[index + 1] if index + 1 < len(occurrences) else None
    prompt = f"""The transcription, order, repeats, target ID, and approximate source location are already final. Do not transcribe, correct, identify, reorder, group, or explain anything.

This attached clip is source seconds {clip_start:.3f}–{clip_end:.3f}. Return a time RELATIVE TO THIS CLIP.
PRECEDING CONTEXT: {json.dumps(previous, ensure_ascii=False) if previous else '(none)'}
TARGET: {json.dumps({**target, 'coarse_source_start': candidate}, ensure_ascii=False)}
FOLLOWING CONTEXT: {json.dumps(following, ensure_ascii=False) if following else '(none)'}

Return only the exact first audible syllable start of TARGET's first repetition. Do not choose another identical occurrence. Mark uncertainty rather than guessing.

Return strict JSON only: {{"occurrence_id":"{target['occurrence_id']}","start":0.0,"uncertainty":""}}"""
    attempts: list[dict[str, Any]] = []
    for attempt in range(3):
        try:
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                   response_schema=single_start_schema(), schema_name="bhakti_single_start",
                                   reasoning_effort="high", max_completion_tokens=4096)
            packet = response["packet"]
            point = clip_start + float(packet["start"])
            uncertainty = str(packet.get("uncertainty", "")).strip().casefold()
            errors = []
            if packet.get("occurrence_id") != target["occurrence_id"]:
                errors.append("response occurrence ID differs from target")
            if not clip_start <= point <= clip_end or abs(point - candidate) > 6.0:
                errors.append("single start is outside the candidate clip")
            if any(marker in uncertainty for marker in ("not_in_clip", "not in clip", "not heard", "unable", "cannot locate")):
                errors.append("single start is not locatable")
            attempts.append({"attempt": attempt + 1, "start": round(point, 3), "uncertainty_note": uncertainty,
                             "response": response, "validation_errors": errors})
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            attempts.append({"attempt": attempt + 1, "error": str(exc), "validation_errors": ["unusable single response"]})
        valid = [item for item in attempts if not item["validation_errors"]]
        if len(valid) == 1 and abs(valid[0]["start"] - candidate) <= 0.5:
            break
        if len(valid) >= 2 and max(item["start"] for item in valid) - min(item["start"] for item in valid) <= 0.5:
            break
    valid = [item for item in attempts if not item["validation_errors"]]
    errors: list[str] = []
    if len(valid) == 1 and abs(valid[0]["start"] - candidate) <= 0.5:
        point = valid[0]["start"]
    elif len(valid) >= 2:
        values = [item["start"] for item in valid]
        point = median(values)
        if max(values) - min(values) > 0.5:
            errors.append("single-start measurements do not agree")
    else:
        point = candidate
        errors.append("single start lacks agreeing evidence")
    response = min(valid, key=lambda item: abs(item["start"] - point))["response"] if valid else attempts[-1].get("response", {"error": "no valid response"})
    return {"kind": "single", "occurrence_id": target["occurrence_id"], "candidate": candidate,
            "start": round(point, 3), "attempts": attempts, "response": response, "validation_errors": errors}



def refine_all_starts(
    audio: Path,
    occurrences: list[dict[str, Any]],
    coarse_sequence: list[dict[str, Any]],
    duration: float,
    options: argparse.Namespace,
    cache_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    chunks = build_timing_chunks(occurrences, coarse_sequence, duration)
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-timing-chunks-") as temporary:
        destination = Path(temporary)
        # Two timing requests at once stay below OpenRouter's shared Gemini
        # burst limit while still overlapping network latency.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
            reports = list(pool.map(
                lambda chunk: refine_timing_chunk(
                    audio, occurrences, chunk, options, destination,
                    cache_dir / f"window-{chunk['index']:03d}.json" if cache_dir else None,
                ),
                chunks,
            ))

    measurements: dict[str, list[float]] = {
        occurrence["occurrence_id"]: [float(coarse_sequence[index]["start"])]
        for index, occurrence in enumerate(occurrences)
    }
    for report in reports:
        if report["validation_errors"]:
            continue
        for entry in report["starts"]:
            measurements[entry["occurrence_id"]].append(entry["start"])
    unresolved = [index for index, occurrence in enumerate(occurrences)
                  if consensus_value(measurements[occurrence["occurrence_id"]], tolerance=0.75) is None]

    recoveries: list[dict[str, Any]] = []
    if len(unresolved) > max(5, len(occurrences) // 5):
        errors = [f"verification disagrees for {len(unresolved)} of {len(occurrences)} occurrences; "
                  "refusing a per-line retry cascade"]
        evidence = reports + [{"kind": "consensus", "starts": [
            {"occurrence_id": occurrence["occurrence_id"],
             "measurements": measurements[occurrence["occurrence_id"]], "start": None}
            for occurrence in occurrences], "validation_errors": errors}]
        return [], evidence, errors
    if unresolved:
        with tempfile.TemporaryDirectory(prefix="bhakti-single-starts-") as temporary:
            destination = Path(temporary)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(unresolved))) as pool:
                recoveries = list(pool.map(
                    lambda index: refine_single_start(audio, occurrences, index, coarse_sequence[index]["start"],
                                                      duration, options, destination), unresolved))
        for report in recoveries:
            if not report["validation_errors"]:
                measurements[report["occurrence_id"]].append(report["start"])

    errors = [f"{report['occurrence_id']}: {error}" for report in recoveries for error in report["validation_errors"]]
    starts: list[float | None] = []
    consensus: list[dict[str, Any]] = []
    for occurrence in occurrences:
        values = measurements[occurrence["occurrence_id"]]
        point = consensus_value(values, tolerance=0.75)
        if point is None:
            errors.append(f"{occurrence['occurrence_id']}: fewer than two agreeing start measurements")
        starts.append(point)
        consensus.append({"occurrence_id": occurrence["occurrence_id"], "measurements": values, "start": point})
    if any(start is None for start in starts) or any(starts[index] <= starts[index - 1] for index in range(1, len(starts))):
        errors.append("consensus starts are missing or non-increasing")

    sequence: list[dict[str, Any]] = []
    if not errors:
        for index, occurrence in enumerate(occurrences):
            start = float(starts[index])
            end = float(starts[index + 1]) if index + 1 < len(starts) else duration
            sequence.append({"occurrence_id": occurrence["occurrence_id"], "ref": occurrence["ref"],
                             "section": occurrence["section"], "repeats": occurrence["repeats"],
                             "start": start, "end": end})
    evidence = reports + recoveries + [{"kind": "consensus", "starts": consensus, "validation_errors": []}]
    return sequence, evidence, errors

def align(song_dir: Path, audited: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "03-timing.json"
    existing = read_packet(target)
    if existing and not options.force and existing.get("publication_status") != "blocked":
        return existing
    packet = audited["packet"]
    occurrences = display_occurrences(packet)
    duration = gemini.duration_seconds(audio)
    if not packet.get("verified_lines") or not occurrences:
        raise RuntimeError("audited transcript lacks canonical lines or performance order")
    with tempfile.TemporaryDirectory(prefix="bhakti-timing-audio-") as temporary:
        model_audio = canonical_timing_audio(audio, Path(temporary) / "timing.m4a")
        if audited.get("segment_audits"):
            coarse_sequence = long_coarse_sequence(audited, occurrences, duration)
            response = {"packet": {"source": "deterministic-segment-hints"}, "usage": {},
                        "resolved_model": "deterministic-segment-hints"}
            errors: list[str] = []
            uncertain: list[str] = []
        else:
            prompt = start_only_timing_prompt(occurrences, duration)
            response = gemini.call(options.model, gemini.key(), prompt, audio=model_audio, timeout=options.timeout,
                                   response_schema=start_only_timing_schema(len(occurrences)),
                                   schema_name="bhakti_start_times", reasoning_effort="high",
                                   max_completion_tokens=min(65536, max(16384, len(occurrences) * 256)))
            coarse_sequence, errors, uncertain = timing_sequence_from_response(occurrences, response["packet"], duration)
        sequence: list[dict[str, Any]] = []
        refinements: list[dict[str, Any]] = []
        if not errors and audited.get("segment_audits"):
            sequence, refinements, refinement_errors = align_long_segments(
                song_dir, model_audio, audited, occurrences, coarse_sequence, duration, options
            )
            errors.extend(refinement_errors)
        elif not errors:
            sequence, refinements, refinement_errors = refine_all_starts(
                model_audio, occurrences, coarse_sequence, duration, options,
                song_dir / ".transcription" / "pipeline" / "timing-windows",
            )
            errors.extend(refinement_errors)
    result = {"duration_seconds": duration, "ordered_occurrences": occurrences, "response": response,
              "coarse_sequence": coarse_sequence, "refinements": refinements,
              "sequence": sequence, "uncertain_occurrence_ids": uncertain,
              "validation_errors": errors, "publication_status": "blocked" if errors else "review-required"}
    write_json(target, result)
    return result

def gloss_surface_errors(lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]]) -> list[str]:
    gloss_by_id = {row.get("id"): row for row in gloss_rows}
    errors: list[str] = []
    for line in lines:
        line_id = line.get("id", "<unknown>")
        words = gloss_by_id.get(line_id, {}).get("word_glosses", [])
        cursor = 0
        folded = "".join(character for character in str(line.get("roman", "")).casefold() if character.isalnum())
        for index, word in enumerate(words):
            token = str(word.get("roman", "")).strip()
            normalized_token = "".join(character for character in token.casefold() if character.isalnum())
            at = folded.find(normalized_token, cursor) if normalized_token else -1
            if not token or not str(word.get("gloss", "")).strip() or at < 0:
                errors.append(f"{line_id} word gloss {index} cannot be mapped to romanized source")
                break
            cursor = at + len(normalized_token)
    return errors


def gloss_contract_errors(lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]]) -> list[str]:
    errors = gloss_surface_errors(lines, gloss_rows)
    gloss_by_id = {row.get("id"): row for row in gloss_rows}
    for line in lines:
        line_id = line.get("id", "<unknown>")
        frame = gloss_by_id.get(line_id, {}).get("semantic_frame")
        if not isinstance(frame, dict) or any(not isinstance(frame.get(field), str) for field in SEMANTIC_FRAME_FIELDS):
            errors.append(f"{line_id} lacks a complete semantic frame")
    return errors


def gloss(song_dir: Path, audited: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "04-glosses.json"
    lines = audited["packet"].get("verified_lines", [])
    existing = read_packet(target)
    if (existing and not options.force and existing.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
            and not gloss_contract_errors(lines, existing.get("packet", {}).get("glosses", []))):
        return existing
    def prompt_for(batch: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
        return f"""Create a literal word-by-word reading of the TARGET audited devotional lyrics. Work line by line and use the surrounding song context.

Create exactly one word_gloss entry for each whitespace-delimited surface token in the supplied roman line, in the identical order. The `roman` value must copy that complete displayed surface token exactly; never split sandhi or a written compound into separate entries, and never substitute an underlying dictionary form. Give the contextually correct primary sense first. A gloss is semantic evidence, not an English draft: do not bake a clumsy phrase such as “cast a glance of mercy” into a token gloss when the phrase-level meaning is “look upon someone with mercy.” Put phrase meaning and idiom in the semantic frame instead.

Before any later translation, explicitly reconstruct the semantic frame: who is acting or experiencing; the action or state; its patient or complement; modifiers; negation or modality; the exact literal image and agency; any established idiom; and how the line connects grammatically to its neighbors. Preserve personification and unusual agency rather than normalizing them. Do not replace one metaphor with another: if a feeling “takes hold,” do not relabel it as kindling or stirring. Preserve a spatial word directly—“inside” remains “inside”—rather than upgrading it to “deep within” unless the source actually expresses depth. Represent reduplication as emphasis or repetition without inventing a new image. Expand relational objects when English requires their complement—a hem is the hem of a garment. Distinguish culturally specific objects precisely, such as an alms bag rather than a generic satchel, and palm/open palm rather than an abstract “hand” when the source requires it. For `raham nazar`, record the phrase-level meaning “look upon someone with mercy,” never “cast a glance.”

Explain internal morphemes inside the token's `gloss` or `grammar_note`. Give a short grammar note for ellipsis, agreement, sandhi, compounds, or syntax. Choose the contextually supported sense of a polysemous word; do not call ordinary dictionary polysemy uncertain. Use uncertainty only when the audited lyric itself remains genuinely unresolved. Do not write a fluent English sentence in this stage.

TARGET LYRICS (return these IDs only):
{json.dumps(batch, ensure_ascii=False)}

NEARBY CONTEXT (do not return these IDs unless also targets):
{json.dumps(context, ensure_ascii=False)}

Return strict JSON:
{{"glosses":[{{"id":"canonical-id","word_glosses":[{{"roman":"exact token","gloss":"contextual literal meaning"}}],"semantic_frame":{{"agent":"","action_or_state":"","patient_or_complement":"","modifiers":"","negation_or_modality":"","literal_image_and_agency":"","idiom_or_phrase":"","cross_line_relation":""}},"grammar_note":"","uncertainty":""}}]}}"""
    schema = {"type": "object", "properties": {"glosses": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"}, "word_glosses": {"type": "array", "items": {"type": "object", "properties": {
                "roman": {"type": "string"}, "gloss": {"type": "string"}},
                "required": ["roman", "gloss"], "additionalProperties": False}},
            "semantic_frame": {"type": "object", "properties": {
                field: {"type": "string"} for field in SEMANTIC_FRAME_FIELDS},
                "required": list(SEMANTIC_FRAME_FIELDS), "additionalProperties": False},
            "grammar_note": {"type": "string"}, "uncertainty": {"type": "string"}},
        "required": ["id", "word_glosses", "semantic_frame", "grammar_note", "uncertainty"], "additionalProperties": False}}},
        "required": ["glosses"], "additionalProperties": False}
    if len(lines) <= 80:
        result = gemini.call(options.model, gemini.key(), prompt_for(lines, []), audio=None, timeout=options.timeout,
                             response_schema=schema, schema_name="bhakti_word_glosses",
                             reasoning_effort="high", max_completion_tokens=65536)
    else:
        batches = [lines[index:index + 40] for index in range(0, len(lines), 40)]
        cache_dir = song_dir / ".transcription" / "pipeline" / "gloss-batches"
        cache_dir.mkdir(parents=True, exist_ok=True)

        def run(index: int) -> dict[str, Any]:
            batch = batches[index]
            expected = [line["id"] for line in batch]
            cache_path = cache_dir / f"batch-{index:03d}.json"
            cached = read_packet(cache_path)
            if cached and cached.get("target_ids") == expected and not options.force:
                cached_rows = cached.get("response", {}).get("packet", {}).get("glosses", [])
                if (cached.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
                        and not gloss_contract_errors(batch, cached_rows)):
                    return cached
            start = index * 40
            context = lines[max(0, start - 2):start] + lines[start + len(batch):start + len(batch) + 2]
            response = gemini.call(options.model, gemini.key(), prompt_for(batch, context), audio=None,
                                   timeout=options.timeout, response_schema=schema,
                                   schema_name="bhakti_word_gloss_batch", reasoning_effort="high",
                                   max_completion_tokens=32768)
            returned = [row.get("id") for row in response["packet"].get("glosses", [])]
            if returned != expected:
                raise RuntimeError(f"gloss batch {index} returned IDs out of order or incomplete")
            mapping_errors = gloss_contract_errors(batch, response["packet"]["glosses"])
            if mapping_errors:
                raise RuntimeError(f"gloss batch {index} violates surface-token mapping: {mapping_errors[:3]}")
            packet = {"target_ids": expected, "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                      "response": response}
            write_json(cache_path, packet)
            return packet

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            packets = list(pool.map(run, range(len(batches))))
        result = {"packet": {"glosses": [row for packet in packets
                                           for row in packet["response"]["packet"]["glosses"]]},
                  "batch_responses": packets, "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                  "resolved_model": options.model}
    result["gloss_contract_version"] = GLOSS_CONTRACT_VERSION
    write_json(target, result)
    return result


def supplied_translation(job: dict[str, Any]) -> str:
    value = job.get("providedTranslation", job.get("provided_translation", ""))
    if not value:
        return "(none supplied)"
    possible_path = Path(str(value)).expanduser()
    return possible_path.read_text(encoding="utf-8") if possible_path.is_file() else str(value)


def translation_review_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"}, "passes": {"type": "boolean"},
            "human_review_recommended": {"type": "boolean"},
            "agency_preserved": {"type": "boolean"}, "imagery_preserved": {"type": "boolean"},
            "all_meaning_accounted_for": {"type": "boolean"},
            "unsupported_additions": {"type": "array", "items": {"type": "string"}},
            "material_choice": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["id", "passes", "human_review_recommended", "agency_preserved", "imagery_preserved",
                     "all_meaning_accounted_for", "unsupported_additions", "material_choice", "reason"],
        "additionalProperties": False}}}, "required": ["reviews"], "additionalProperties": False}


def independently_review_translations(
    song_dir: Path, lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]],
    translation_rows: list[dict[str, Any]], provided_translation: str, options: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gloss_by_id = {row["id"]: row for row in gloss_rows}
    translation_by_id = {row["id"]: row for row in translation_rows}
    batches = [lines[index:index + 40] for index in range(0, len(lines), 40)]
    cache_dir = song_dir / ".transcription" / "pipeline" / "translation-review-batches"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def run(index: int) -> dict[str, Any]:
        batch = batches[index]
        expected = [line["id"] for line in batch]
        evidence = [{"source": line, "gloss": gloss_by_id[line["id"]],
                     "draft": translation_by_id[line["id"]]} for line in batch]
        fingerprint = hashlib.sha256(json.dumps(
            {"version": TRANSLATION_INPUT_VERSION, "model": options.model, "evidence": evidence,
             "provided_translation": provided_translation}, ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest()
        path = cache_dir / f"batch-{index:03d}.json"
        cached = read_packet(path)
        if cached and cached.get("fingerprint") == fingerprint and not options.force:
            return cached
        prompt = f"""Act as an independent adversarial reviewer of devotional translations. You did not write the drafts. Do not rewrite them and do not optimize style.

For each line, compare the draft against the indexed glosses, semantic frame, grammar, source, neighboring relation, and material alternatives. Check separately: grammatical agency/experiencer; literal image and metaphor; every negation, modality, modifier and emphasis; unsupported additions; and whether two defensible readings differ materially in agency, metaphor, ambiguity, or poetic force.

Conventional English is not automatically better. Preserve personification, repetition, transparent spatial language, and concrete ritual images. A breath that abandons a speaker is materially different from a speaker releasing breath; “takes hold” is materially different from “kindles”; palm is materially different from an abstract inner state. If the draft and an alternative make such a material choice and no locked human baseline resolves it, set human_review_recommended=true. Do not flag trivial synonyms or punctuation.

If a locked human translation is supplied and the draft copies it exactly, do not fail or rewrite it. If it conflicts with lexical evidence, keep passes=true but set human_review_recommended=true and explain the conflict for the human.

Set passes=false for lost meaning, changed agency/image, or unsupported additions. Return these IDs once in order. Strict JSON only.

EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)}

LOCKED HUMAN TRANSLATION (or none):
{provided_translation}"""
        response = gemini.call(options.model, gemini.key(), prompt, audio=None, timeout=options.timeout,
                               response_schema=translation_review_schema(), schema_name="bhakti_translation_review",
                               reasoning_effort="high", max_completion_tokens=32768)
        observed = [row.get("id") for row in response["packet"].get("reviews", [])]
        if observed != expected:
            raise RuntimeError(f"translation review batch {index} returned IDs out of order or incomplete")
        result = {"fingerprint": fingerprint, "target_ids": expected, "response": response}
        write_json(path, result)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(batches))) as pool:
        packets = list(pool.map(run, range(len(batches))))
    reviews = [row for packet in packets for row in packet["response"]["packet"]["reviews"]]
    return reviews, packets


def translate(song_dir: Path, audited: dict[str, Any], glosses: dict[str, Any], job: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "05-translation.json"
    existing = read_packet(target)
    if existing and not options.force and existing.get("input_contract_version") == TRANSLATION_INPUT_VERSION:
        return existing
    lines = audited['packet'].get('verified_lines', [])
    gloss_rows = glosses['packet'].get('glosses', [])
    gloss_by_id = {row['id']: row for row in gloss_rows}
    provided_translation = supplied_translation(job)
    provided_rule = ("A human translation is supplied and LOCKED. Copy its wording exactly for every matching line; "
                     "do not silently correct or polish it in this stage. If lexical evidence appears to conflict with it, "
                     "preserve the supplied wording, set human_review_recommended=true, and explain the conflict in choice_note."
                     if provided_translation != "(none supplied)" else
                     "No human translation is supplied; choose the closest supported English and expose material alternatives.")

    def prompt_for(batch: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
        batch_glosses = [gloss_by_id[line['id']] for line in batch]
        return f"""Write faithful, complete English translations from the supplied word glosses, semantic frames, and grammar notes ONLY. The semantic frame is authoritative for agency, action/state, patient/complement, negation/modality, literal image, idiom, and cross-line syntax. Do not introduce a looser synonym, devotional interpretation, or omission that it does not support.

For each line, reason in this order before choosing the final English:
1. Compose the indexed token glosses into the closest grammatical English scaffold.
2. Check the scaffold against every semantic-frame field and neighboring line.
3. Preserve the source's agent and experiencer exactly. Never change “my breath abandons me” into “I breathe my last,” a deity dwelling in a palm into an abstract spiritual state, or an interior image into a generic emotion merely because the alternative is conventional English.
4. Apply an established idiom only when `idiom_or_phrase` identifies it and the idiom does not erase a deliberate image. The devotional phrase `raham nazar` means “look upon [someone] with mercy”; do not render it as “cast a glance.” Conversely, do not invent a replacement metaphor such as “kindle” or “stir” when the source image is that a feeling “takes hold.” A possessed relational noun such as a garment hem should remain explicit rather than becoming an ambiguous “your hem.”
5. Make only the smallest grammatical adjustments needed for intelligible English. Prefer the source's transparent spatial vocabulary (“from the inside”) over a smoother intensifying substitute (“deep within”) unless depth is lexically present. Literal and poetic force outrank smoothness.

For each line, return plain literal English plus ordered display segments. Read adjacent lines as a continuous utterance before deciding syntax, punctuation, ellipsis, pronouns, or repeated words; a line may be a deliberate grammatical continuation. Each segment may reference the exact word indices which support it; punctuation or necessary English function-word segments can use an empty index list.

Write lucid devotional English, but do not confuse conventional English with better poetry. Literal strangeness, repetition, personification, unusual agency, and concrete bodily or ritual imagery may be the point. Preserve a supported image such as “my breath will abandon me” even if an English idiom such as “I will breathe my last” sounds smoother. Never replace the source's agency, metaphor, ambiguity, or emotional logic merely to sound idiomatic. Correct wording only when it is demonstrably wrong, ungrammatical, or obstructs understanding. Avoid legalistic filler, accidental inversion, duplicate modifiers, and unsupported editorial verbs. Retain darshan or sacred vision, an alms bag, garment hem, cupped or open palm, lotus, dust, ocean, threshold, cage, and Mount Meru when the source supports them.

Resolve ordinary polysemy from the supplied grammar/song context. When two defensible renderings differ materially in agency, metaphor, ambiguity, or poetic force, include both in `material_alternatives` and set `human_review_recommended=true` instead of silently optimizing for smoothness. This is not required for trivial synonyms. The completed segments must reconstruct `literal_english` exactly, including ordinary spacing and punctuation. Then report a fidelity check: whether agency/image and all source meaning were preserved, every unsupported addition (normally none), and a concise note naming any nonliteral idiom or necessary English function word.

TARGET audited source lines (return these IDs only):
{json.dumps(batch, ensure_ascii=False)}

TARGET word gloss record:
{json.dumps(batch_glosses, ensure_ascii=False)}

NEARBY source context (do not return these IDs unless also targets):
{json.dumps(context, ensure_ascii=False)}

HUMAN-TRANSLATION RULE:
{provided_rule}

Supplied translation:
{provided_translation}

Return strict JSON:
{{"translations":[{{"id":"canonical-id","literal_english":"","segments":[{{"text":"","word_indices":[]}}],"material_alternatives":[],"human_review_recommended":false,"choice_note":"","fidelity":{{"agency_and_image_preserved":true,"all_meaning_accounted_for":true,"unsupported_additions":[],"notes":""}},"uncertainty":""}}],"comparison":[{{"id":"canonical-id","supplied":"","chosen":"","material_change":false,"reason":""}}]}}"""
    schema = {"type": "object", "properties": {
        "translations": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "literal_english": {"type": "string"},
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "word_indices": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "word_indices"], "additionalProperties": False}},
            "fidelity": {"type": "object", "properties": {
                "agency_and_image_preserved": {"type": "boolean"},
                "all_meaning_accounted_for": {"type": "boolean"},
                "unsupported_additions": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"}},
                "required": ["agency_and_image_preserved", "all_meaning_accounted_for", "unsupported_additions", "notes"],
                "additionalProperties": False},
            "material_alternatives": {"type": "array", "items": {"type": "string"}},
            "human_review_recommended": {"type": "boolean"},
            "choice_note": {"type": "string"},
            "uncertainty": {"type": "string"}},
            "required": ["id", "literal_english", "segments", "material_alternatives", "human_review_recommended", "choice_note", "fidelity", "uncertainty"], "additionalProperties": False}},
        "comparison": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "supplied": {"type": "string"}, "chosen": {"type": "string"},
            "material_change": {"type": "boolean"}, "reason": {"type": "string"}},
            "required": ["id", "supplied", "chosen", "material_change", "reason"], "additionalProperties": False}},
    }, "required": ["translations", "comparison"], "additionalProperties": False}
    if len(lines) <= 80:
        result = gemini.call(options.model, gemini.key(), prompt_for(lines, []), audio=None, timeout=options.timeout,
                             response_schema=schema, schema_name="bhakti_literal_translation",
                             reasoning_effort="high", max_completion_tokens=65536)
    else:
        batches = [lines[index:index + 40] for index in range(0, len(lines), 40)]
        cache_dir = song_dir / ".transcription" / "pipeline" / "translation-batches"
        cache_dir.mkdir(parents=True, exist_ok=True)

        def run(index: int) -> dict[str, Any]:
            batch = batches[index]
            expected = [line["id"] for line in batch]
            cache_path = cache_dir / f"batch-{index:03d}.json"
            cached = read_packet(cache_path)
            if (cached and cached.get("target_ids") == expected
                    and cached.get("input_contract_version") == TRANSLATION_INPUT_VERSION and not options.force):
                return cached
            start = index * 40
            context = lines[max(0, start - 2):start] + lines[start + len(batch):start + len(batch) + 2]
            response = gemini.call(options.model, gemini.key(), prompt_for(batch, context), audio=None,
                                   timeout=options.timeout, response_schema=schema,
                                   schema_name="bhakti_translation_batch", reasoning_effort="high",
                                   max_completion_tokens=32768)
            returned = [row.get("id") for row in response["packet"].get("translations", [])]
            compared = [row.get("id") for row in response["packet"].get("comparison", [])]
            if returned != expected or compared != expected:
                raise RuntimeError(f"translation batch {index} returned IDs out of order or incomplete")
            packet = {"target_ids": expected, "input_contract_version": TRANSLATION_INPUT_VERSION,
                      "response": response}
            write_json(cache_path, packet)
            return packet

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            packets = list(pool.map(run, range(len(batches))))
        result = {"packet": {
                      "translations": [row for packet in packets
                                       for row in packet["response"]["packet"]["translations"]],
                      "comparison": [row for packet in packets
                                     for row in packet["response"]["packet"]["comparison"]],
                  }, "batch_responses": packets, "input_contract_version": TRANSLATION_INPUT_VERSION,
                  "resolved_model": options.model}
    result["input_contract_version"] = TRANSLATION_INPUT_VERSION
    independent_reviews, review_packets = independently_review_translations(
        song_dir, lines, gloss_rows, result["packet"]["translations"], provided_translation, options
    )
    review_by_id = {row["id"]: row for row in independent_reviews}
    for row in result["packet"]["translations"]:
        row["independent_review"] = review_by_id[row["id"]]
    result["review_responses"] = review_packets
    write_json(target, result)
    return result


def validate_ids(lines: list[dict[str, Any]], *collections: list[dict[str, Any]]) -> list[str]:
    expected = {line.get("id") for line in lines}
    errors: list[str] = []
    for items in collections:
        got = {item.get("id") for item in items}
        if got != expected:
            errors.append(f"line id mismatch: expected {sorted(expected)}, got {sorted(got)}")
    return errors


def validate_line_contract(lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]], translation_rows: list[dict[str, Any]]) -> list[str]:
    """Validate the fields the browser needs without guessing missing text."""
    errors: list[str] = gloss_surface_errors(lines, gloss_rows)
    gloss_by_id = {row.get("id"): row for row in gloss_rows}
    translation_by_id = {row.get("id"): row for row in translation_rows}
    for line in lines:
        line_id = line.get("id", "<unknown>")
        source, roman = str(line.get("source_text", "")).strip(), str(line.get("roman", "")).strip()
        if not source or not roman:
            errors.append(f"{line_id} lacks required source script or romanization")
        words = gloss_by_id.get(line_id, {}).get("word_glosses", [])
        if not isinstance(words, list) or not words:
            errors.append(f"{line_id} lacks word glosses")
            continue
        translation = translation_by_id.get(line_id, {})
        if not str(translation.get("literal_english", "")).strip():
            errors.append(f"{line_id} lacks a literal English line")
        fidelity = translation.get("fidelity", {})
        if fidelity:
            if not fidelity.get("agency_and_image_preserved"):
                errors.append(f"{line_id} translation does not preserve agency or imagery")
            if not fidelity.get("all_meaning_accounted_for"):
                errors.append(f"{line_id} translation does not account for every source meaning")
            if fidelity.get("unsupported_additions"):
                errors.append(f"{line_id} translation contains unsupported additions")
        if translation.get("human_review_recommended"):
            errors.append(f"{line_id} translation has a material poetic choice requiring review")
        independent = translation.get("independent_review", {})
        if independent:
            if not independent.get("passes"):
                errors.append(f"{line_id} independent translation review failed")
            if not independent.get("agency_preserved") or not independent.get("imagery_preserved"):
                errors.append(f"{line_id} independent review found changed agency or imagery")
            if not independent.get("all_meaning_accounted_for"):
                errors.append(f"{line_id} independent review found omitted meaning")
            if independent.get("unsupported_additions"):
                errors.append(f"{line_id} independent review found unsupported additions")
            if independent.get("human_review_recommended"):
                errors.append(f"{line_id} independent review requires a human poetic choice")
        for segment in translation.get("segments", []):
            for word_index in segment.get("word_indices", []):
                if not isinstance(word_index, int) or not 0 <= word_index < len(words):
                    errors.append(f"{line_id} English segment uses invalid word index {word_index!r}")
    return errors


def segment_english(parts: list[dict[str, Any]], fallback: str) -> str:
    if not parts:
        return fallback
    rendered: list[str] = []
    previous_text = ""
    for part in parts:
        text = str(part.get("text", ""))
        if previous_text.rstrip().endswith(("-", "—", "…", "/", "(", '"', "“", "‘")):
            text = text.lstrip()
        if (rendered and text and not text[0].isspace() and text[0] not in ",.;:!?…’')]}"
                and not previous_text.endswith(" ")
                and not previous_text.rstrip().endswith(("-", "—", "…", "/", "(", '"', "“", "‘"))):
            text = " " + text
        indices = [str(index) for index in part.get("word_indices", []) if isinstance(index, int) and index >= 0]
        rendered.append("{" + ",".join(indices) + ":" + text + "}" if indices else text)
        previous_text = text
    return "".join(rendered)


def language_code(language: str) -> str:
    return {"Hindi": "hi", "Sanskrit": "sa", "Punjabi": "pa", "Kannada": "kn", "Marathi": "mr"}.get(language, "")


def reviewed_display_title(candidate: str, lines: list[dict[str, Any]]) -> str:
    """Prefer the audited scholarly lyric when it is evidently the source title."""
    if not candidate or not lines:
        return candidate
    first = str(lines[0].get("roman", "")).strip()
    source_key = naming.compact(naming.common_romanization(candidate))
    lyric_key = naming.compact(naming.common_romanization(first))
    similar = difflib.SequenceMatcher(None, source_key, lyric_key).ratio()
    if first and similar >= 0.88 and abs(len(source_key.split()) - len(lyric_key.split())) <= 1:
        return first.title()
    return candidate


def page_html(meta: dict[str, Any]) -> str:
    title = meta["title"]
    credit = meta.get("pageCredit") or meta.get("credit", "")
    subtitle = meta.get("subtitle", "")
    escape = lambda text: str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sub = f'      <p class="song-attrib"><em>{escape(subtitle)}</em></p>\n' if subtitle else ""
    cred = f'      <p class="song-credit">{escape(credit)}</p>\n' if credit else ""
    audio_sources = meta.get("audioSources") or [{"src": "audio.m4a", "type": "audio/mp4"}]
    source_html = "".join(f'<source src="{escape(source["src"])}" type="{escape(source["type"])}">' for source in audio_sources)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=2" />
  <meta name="theme-color" content="#6b0e16" />
  <link rel="icon" type="image/svg+xml" href="../../assets/favicon.svg" />
  <link rel="apple-touch-icon" href="../../assets/favicon.png" />
  <link rel="manifest" href="../../manifest.webmanifest" />
  <meta name="robots" content="noindex,nofollow,noarchive,nosnippet,noimageindex" />
  <meta name="referrer" content="no-referrer" />
  <title>{escape(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Cormorant+Garamond:ital,wght@0,300..700;1,300..700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../../assets/style.css" />
  <link rel="stylesheet" href="../../assets/song.css" />
</head>
<body>
  <main class="song-page">
    <header class="song-hero">
      <h1 class="song-title">{escape(title)}</h1>
{sub}{cred}      <p class="song-hint">Tap or hover over any word to see its meaning.</p>
    </header>
    <section class="song-root" id="songRoot" aria-live="polite"></section>
  </main>
  <div class="audio-player" id="audioPlayer">
    <a class="song-home" href="/" aria-label="All songs" title="All songs"><svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M4 10.5 12 4l8 6.5V20h-5v-6H9v6H4v-9.5Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg></a>
    <button class="ap-btn" id="apPlayPause" type="button" aria-label="Play"><svg class="ap-icon ap-icon-play" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg><svg class="ap-icon ap-icon-pause" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor"/></svg></button>
    <div class="ap-progress" id="apProgress"><div class="ap-progress-bar" id="apProgressBar"></div></div>
    <div class="ap-time" id="apTime" aria-label="Playback time"><span id="apElapsed">0:00</span><span class="ap-time-sep">/</span><span class="ap-time-total" id="apDuration">—:—</span></div>
    <audio id="songAudio" preload="metadata">{source_html}</audio>
  </div>
  <script src="data.js?v=contract-20260820-5"></script>
  <script src="../../assets/song.js?v=contract-20260820-5"></script>
  <script>if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");</script>
</body>
</html>
'''


def load_catalogue() -> list[dict[str, Any]]:
    path = ROOT / "data" / "songs.js"
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.BHAKTI_SONGS));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, text=True, capture_output=True).stdout
    value = json.loads(output)
    return value if isinstance(value, list) else []


def publication_errors(audited: dict[str, Any], timing: dict[str, Any], glosses: dict[str, Any], translations: dict[str, Any]) -> list[str]:
    lines = audited["packet"].get("verified_lines", [])
    gloss_rows = glosses["packet"].get("glosses", [])
    translation_rows = translations["packet"].get("translations", [])
    errors = validate_ids(lines, gloss_rows, translation_rows)
    errors.extend(validate_line_contract(lines, gloss_rows, translation_rows))
    if timing.get("validation_errors"):
        errors.extend(timing["validation_errors"])
    if audited["packet"].get("uncertainties"):
        errors.append("audited transcription has unresolved uncertainties")
    if any(str(row.get("uncertainty") or "").strip().casefold() not in {"", "none", "no", "null", "n/a"}
           for row in gloss_rows + translation_rows):
        errors.append("gloss or translation has unresolved uncertainty")
    return errors


def generate(song_dir: Path, job: dict[str, Any], source: dict[str, Any], audited: dict[str, Any], timing: dict[str, Any], glosses: dict[str, Any], translations: dict[str, Any]) -> None:
    errors = publication_errors(audited, timing, glosses, translations)
    if errors:
        raise RuntimeError("publication blocked: " + "; ".join(errors))
    lines = audited["packet"].get("verified_lines", [])
    gloss_rows = glosses["packet"].get("glosses", [])
    translation_rows = translations["packet"].get("translations", [])
    gloss_by_id = {row["id"]: row for row in gloss_rows}
    translation_by_id = {row["id"]: row for row in translation_rows}
    meta_from_model = audited["packet"].get("metadata", {})
    raw_title = job.get("title") or source.get("title") or job["slug"].replace("-", " ").title()
    title = reviewed_display_title(str(raw_title), lines)
    # Do not manufacture a public role from a model candidate. Callers may
    # supply researched roles; otherwise the compact credit line is absent.
    writer = str(job.get("writer", "")).strip()
    singer = str(job.get("singer") or source.get("artist") or "").strip()
    composer = str(job.get("composer") or source.get("composer") or "").strip()
    distinct_people = list(dict.fromkeys(person for person in (writer, singer, composer) if person))
    credit = str(job.get("credit", "")).strip() or " · ".join(distinct_people)
    page_credit = str(job.get("pageCredit", "")).strip() or singer or credit
    subjects = job.get("subjectTags", [])
    subtitle = str(job.get("subtitle", "")).strip() or (subjects[0] if subjects else "")
    aliases = naming.search_aliases(
        [job["slug"].replace("-", " "), title, subtitle, credit, page_credit,
         writer, singer, composer, *subjects, *(job.get("languages") or meta_from_model.get("languages", []))],
        job.get("searchAliases") or [],
    )
    languages = list(dict.fromkeys(normalized_language(str(language))
                                   for language in (job.get("languages") or meta_from_model.get("languages", []))
                                   if str(language).strip()))
    meta = {"title": title, "subtitle": subtitle, "credit": credit, "pageCredit": page_credit,
            "writer": writer, "singer": singer, "composer": composer,
            "languages": languages,
            "subjectTags": subjects, "searchAliases": aliases,
            "audioSources": listener_audio_sources(song_dir),
            "timingStatus": "start-only-reviewed",
            "translationStatus": "gloss-derived literal",
            "sourceStatus": "reviewed"}
    line_data: dict[str, Any] = {}
    for line in lines:
        line_id = line["id"]
        row = translation_by_id[line_id]
        line_data[line_id] = {"source": line.get("source_text", ""), "sourceLanguage": language_code((meta["languages"] or [""])[0]),
                              "roman": line.get("roman", ""), "english": segment_english(row.get("segments", []), row.get("literal_english", "")),
                              "words": gloss_by_id[line_id].get("word_glosses", []), "grammarNote": gloss_by_id[line_id].get("grammar_note", "")}
    sequence = [{"ref": event["ref"], "section": next((line.get("kind", "verse") for line in lines if line["id"] == event["ref"]), "verse"), "repeats": 1}
                for event in timing["sequence"]]
    times = [{"start": round(event["start"], 3), "end": round(event["end"], 3)} for event in timing["sequence"]]
    data = ("window.SONG_META = " + json.dumps(meta, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_LINES = " + json.dumps(line_data, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_SEQUENCE = " + json.dumps(sequence, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_TIMINGS = " + json.dumps(times, ensure_ascii=False, indent=2) + ";\n")
    (song_dir / "data.js").write_text(data, encoding="utf-8")
    (song_dir / "index.html").write_text(page_html(meta), encoding="utf-8")
    catalogue = load_catalogue()
    entry = {"slug": job["slug"], "title": title, "credit": credit,
             "languageTags": meta["languages"], "subjectTags": meta["subjectTags"],
             "searchAliases": aliases}
    if meta["subtitle"]:
        entry["subtitle"] = meta["subtitle"]
    catalogue = [song for song in catalogue if song.get("slug") != job["slug"]] + [entry]
    (ROOT / "data" / "songs.js").write_text("window.BHAKTI_SONGS = " + json.dumps(catalogue, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def reported_cost(*artifacts: Any) -> float | None:
    """Total only provider-reported cost fields; never invent a price estimate."""
    total = 0.0
    seen = False
    stack = list(artifacts)
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            usage = value.get("usage")
            if isinstance(usage, dict) and isinstance(usage.get("cost"), (int, float)):
                total += float(usage["cost"])
                seen = True
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return round(total, 8) if seen else None


def run_one(job: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    song_dir, source = intake(job, force=options.force)
    if "youtube.com" in str(source.get("source_url", "")) or "youtu.be" in str(source.get("source_url", "")):
        trim = detect_youtube_trim(song_dir, source, options)
        apply_lossless_trim(song_dir, trim)
    audio = preferred_listener_audio(song_dir)
    started = time.time()
    raw = transcript(song_dir, source, audio, options)
    audited = audit_transcript(song_dir, raw, audio, options)
    timing = align(song_dir, audited, audio, options)
    glosses = gloss(song_dir, audited, options)
    translations = translate(song_dir, audited, glosses, job, options)
    errors = publication_errors(audited, timing, glosses, translations)
    status = "blocked" if errors else "review-required"
    packet = {"source": source, "model_requested": options.model, "created_at": time.time(), "transcript": raw,
              "audit": audited, "timing": timing, "glosses": glosses, "translation": translations,
              "publication_status": status, "validation_errors": errors,
              "elapsed_seconds": round(time.time() - started, 2),
              "reported_openrouter_cost": reported_cost(raw, audited, timing, glosses, translations)}
    write_json(song_dir / ".transcription" / "pipeline" / "song-packet.json", packet)
    return {"slug": job["slug"], "status": packet["publication_status"], "elapsed_seconds": packet["elapsed_seconds"],
            "reported_openrouter_cost": packet["reported_openrouter_cost"]}


def main() -> int:
    options = parse_args()
    jobs = normalise_jobs(options)
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        futures = {pool.submit(run_one, job, options): job["slug"] for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            slug = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # retain other batch results but exit non-zero
                results.append({"slug": slug, "status": "blocked", "error": str(exc)})
    if options.publish:
        # API stages above may run concurrently. Writing the shared catalogue
        # is deliberately serialized so parallel songs cannot lose entries.
        for job in jobs:
            result = next(item for item in results if item["slug"] == job["slug"])
            if result["status"] == "blocked":
                continue
            song_dir = ROOT / "songs" / job["slug"]
            packet_dir = song_dir / ".transcription" / "pipeline"
            source = read_packet(song_dir / ".transcription" / "source.json") or {}
            audited = read_packet(packet_dir / "02-transcript-audit.json")
            timing = read_packet(packet_dir / "03-timing.json")
            glosses = read_packet(packet_dir / "04-glosses.json")
            translations = read_packet(packet_dir / "05-translation.json")
            try:
                if not all((audited, timing, glosses, translations)):
                    raise RuntimeError(f"missing pipeline artifact for {job['slug']}")
                generate(song_dir, job, source, audited, timing, glosses, translations)
                summary = read_packet(packet_dir / "song-packet.json") or {}
                summary["publication_status"] = "generated"
                write_json(packet_dir / "song-packet.json", summary)
                result["status"] = "generated"
            except Exception as exc:
                result["status"] = "blocked"
                result["error"] = str(exc)
    print(json.dumps(sorted(results, key=lambda item: item["slug"]), ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "blocked" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
