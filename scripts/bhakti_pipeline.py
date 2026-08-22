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
import gloss_policy
import naming
import resolve_youtube_music_audio as ytmusic
import tag_taxonomy
import source_word_map
import source_witness


ROOT = Path(__file__).resolve().parents[1]
MODEL = gemini.MODEL
LONG_MERGE_VERSION = 7
LONG_TRANSCRIPT_CONTRACT_VERSION = 1
GLOSS_CONTRACT_VERSION = 4
TRANSLATION_INPUT_VERSION = 7
SEMANTIC_FRAME_FIELDS = (
    "agent", "action_or_state", "patient_or_complement", "modifiers",
    "negation_or_modality", "literal_image_and_agency", "idiom_or_phrase",
    "cross_line_relation",
)


def preserved_term_registry() -> dict[str, Any]:
    return json.loads((ROOT / "data" / "preserved_terms.json").read_text(encoding="utf-8"))


def economy_model(model: str) -> str:
    return model if model.endswith(":batch") else model + ":batch"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--song", action="append", default=[], metavar="SLUG=SOURCE",
                        help="Local audio path or yt-dlp URL. Repeat for a batch.")
    parser.add_argument("--url", action="append", default=[],
                        help="YouTube/media URL with automatic slug, title, and description-credit extraction. Repeat for a batch.")
    parser.add_argument("--batch", type=Path,
                        help="JSON: {songs:[{slug, source, title?, writer?, singer?, composer?, languages?, subjectTags?, searchAliases?}]}")
    parser.add_argument("--workers", type=int, default=7,
                        help="Independent songs to process concurrently (default: 7; outbound API calls are separately rate-gated).")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--economy", action="store_true",
                        help="Use synchronous Gemini for audio stages and half-price OpenRouter Batch for text-only stages.")
    parser.add_argument("--publish", action="store_true",
                        help="Generate readers and update data/songs.js after all required checks pass.")
    parser.add_argument("--generate-only", action="store_true",
                        help="Publish existing reviewed artifacts without running or paying for API stages; implies --publish.")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--force", action="store_true", help="Rerun cached API stages for an existing intake.")
    parser.add_argument("--source-witness-audit", action="store_true",
                        help="Rerun only the transcript-audit-and-downstream stages with an identified textual witness; preserves the first audio transcript and listener master.")
    parser.add_argument("--refresh-timing", action="store_true",
                        help="Rerun only lyric-aware onset alignment; preserves verified transcript, glosses, and translation.")
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_packet(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def apply_verified_text_corrections(song_dir: Path, audited: dict[str, Any]) -> bool:
    """Apply source-and-audio-confirmed corrections after every audit.

    This registry is reviewed evidence, never model output. It prevents a
    future regeneration from restoring an earlier mishearing.
    """
    registry = read_packet(ROOT / "data" / "verified_text_corrections.json") or {}
    changes = registry.get("songs", {}).get(song_dir.name, {}).get("lines", {})
    lines = {line.get("id"): line for line in audited.get("packet", {}).get("verified_lines", [])}
    changed = False
    for line_id, correction in changes.items():
        line = lines.get(line_id)
        if not line:
            continue
        for key in ("source_text", "roman"):
            value = correction.get(key)
            if isinstance(value, str) and line.get(key) != value:
                line[key] = value
                changed = True
        note = correction.get("verification")
        if isinstance(note, str) and note and note not in str(line.get("translation_notes") or ""):
            line["translation_notes"] = (str(line.get("translation_notes") or "").strip() + " " + note).strip()
            changed = True
    return changed


def is_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def is_youtube_or_query(value: str) -> bool:
    return ytmusic.looks_like_youtube_reference(value) or (not is_url(value) and not Path(value).expanduser().exists())


def media_metadata(reference: str) -> dict[str, Any]:
    result = subprocess.run(
        ["yt-dlp", "-4", "--no-playlist", "--dump-single-json", "--skip-download", reference],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip()[-2000:] or "yt-dlp returned no diagnostic"
        raise RuntimeError(f"media metadata extraction failed for {reference}: {detail}")
    return json.loads(result.stdout)


def embedded_audio_metadata(path: Path) -> dict[str, Any]:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=title,artist,album,composer,genre,date,track",
                             "-of", "json", str(path)], check=True, capture_output=True, text=True)
    tags = json.loads(result.stdout).get("format", {}).get("tags", {})
    return {str(key).casefold(): value for key, value in tags.items() if value not in (None, "")}


def source_credit_override(metadata: dict[str, Any]) -> dict[str, Any]:
    registry_path = ROOT / "data" / "source_credits.json"
    if not registry_path.is_file():
        return {}
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    value = registry.get("sources", {}).get(str(metadata.get("id") or ""), {})
    return value if isinstance(value, dict) else {}


def normalise_jobs(options: argparse.Namespace) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for spec in options.song:
        if "=" not in spec:
            raise SystemExit("--song must be SLUG=SOURCE")
        slug, source = spec.split("=", 1)
        jobs.append({"slug": slug.strip(), "source": source.strip()})
    for url in getattr(options, "url", []):
        supplied_id = ytmusic.extract_video_id(url)
        supplied_override = source_credit_override({"id": supplied_id}) if supplied_id else {}
        keep_original = bool(supplied_override.get("keepOriginal"))
        resolved = ytmusic.resolve_reference(url) if is_youtube_or_query(url) and not keep_original else None
        source_value = resolved["resolved_url"] if resolved else url
        metadata = media_metadata(source_value)
        fields: dict[str, str] = {}
        for line in str(metadata.get("description") or "").splitlines():
            match = re.match(r"\s*([^:]{2,30})\s*:\s*(.+?)\s*$", line)
            if match:
                fields[match.group(1).strip().casefold()] = match.group(2).strip()
        raw_title = str(metadata.get("title") or metadata.get("id") or "song")
        override = supplied_override or source_credit_override(metadata)
        title = (override.get("title") or fields.get("song")
                 or re.sub(r"\s+with lyrics\b.*$", "", raw_title.split("|")[0], flags=re.I).strip())
        source_artist = str(metadata.get("uploader") or metadata.get("channel") or "").strip()
        title_artist = source_artist if (source_artist and naming.compact(source_artist) in naming.compact(raw_title)) else ""
        writer = (override.get("writer") or fields.get("lyricist") or fields.get("lyrics")
                  or fields.get("poet") or fields.get("author") or fields.get("written by") or "")
        singer = (override.get("singer") or fields.get("artist") or fields.get("singer")
                  or fields.get("sung by") or fields.get("vocalist") or title_artist)
        composer = (override.get("composer") or fields.get("music director") or fields.get("composer")
                    or fields.get("composed") or fields.get("music") or "")
        jobs.append({"slug": naming.slugify(title), "source": metadata.get("webpage_url") or source_value,
                     "title": title, "displayTitle": str(override.get("displayTitle") or ""), "subtitle": fields.get("album", ""),
                     "writer": writer, "singer": singer, "vocalist": str(override.get("vocalist") or ""),
                     "ensemble": str(override.get("ensemble") or ""), "composer": composer,
                     "languages": list(override.get("languages") or []),
                     "subjectTags": list(override.get("subjectTags") or []),
                     "searchAliases": [raw_title, *(override.get("searchAliases") or [])], "_source_metadata": metadata,
                     "_source_resolution": resolved, "_keep_original": keep_original})
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
        # A cancelled/failed URL fetch may have created only the private review
        # directory. That empty scaffold contains no media or public data and
        # is safe to resume; never overwrite an actual partial reader instead.
        entries = list(song_dir.iterdir())
        resumable_empty_scaffold = all(
            entry.name == ".transcription" and entry.is_dir() and not any(entry.iterdir())
            for entry in entries
        )
        if not resumable_empty_scaffold:
            raise RuntimeError(f"refusing to overwrite non-empty {song_dir}")
    song_dir.mkdir(parents=True, exist_ok=True)
    review_dir = song_dir / ".transcription"
    review_dir.mkdir(exist_ok=True)
    source_value = job["source"]
    if is_youtube_or_query(source_value):
        if job.get("_keep_original"):
            resolution = None
            source_value = ytmusic.canonicalize_reference(source_value)
        else:
            resolution = job.get("_source_resolution") or ytmusic.resolve_reference(source_value)
            source_value = str(resolution["resolved_url"])
    else:
        resolution = None
    if is_url(source_value):
        metadata = job.get("_source_metadata") or media_metadata(source_value)
        source = {
            "source_url": metadata.get("webpage_url") or source_value,
            "title": metadata.get("title"), "uploader": metadata.get("uploader"),
            "channel": metadata.get("channel"), "upload_date": metadata.get("upload_date"),
            "duration_seconds": metadata.get("duration"), "description": metadata.get("description"),
            "extractor_key": metadata.get("extractor_key"), "id": metadata.get("id"),
            "source_resolution": resolution,
            "review_note": "Source metadata is evidence to verify, never automatic public credit.",
        }
        subprocess.run(["yt-dlp", "-4", "--no-playlist", "-f", "bestaudio", "-o", str(song_dir / "audio.%(ext)s"), source_value], check=True)
        originals = [path for path in song_dir.glob("audio.*") if path.suffix not in {".part", ".ytdl"}]
        if len(originals) != 1:
            raise RuntimeError(f"expected one best-audio download from {source_value}, found {len(originals)}")
        primary = originals[0]
        if primary.suffix.casefold() != ".m4a":
            try:
                subprocess.run(["yt-dlp", "-4", "--no-playlist", "-f", "bestaudio[ext=m4a]", "-o", str(audio), source_value], check=True)
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
                  "source_url": job.get("sourceUrl"),
                  "source_resolution": job.get("sourceResolution"),
                  "review_note": "Local file metadata is evidence to verify, never automatic public credit."}
    write_json(review_dir / "source.json", source)
    return song_dir, source


def audio_stream_quality(path: Path) -> tuple[int, bool]:
    """Return approximate audio bitrate and whether the container is audio-only."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate:stream=codec_type,bit_rate",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
        )
        payload = json.loads(probe.stdout)
        streams = payload.get("streams", [])
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        rate = max((int(stream.get("bit_rate") or 0) for stream in audio_streams), default=0)
        if not rate:
            rate = int((payload.get("format") or {}).get("bit_rate") or 0)
        return rate, bool(audio_streams) and len(audio_streams) == len(streams)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
        return 0, True


def listener_audio_sources(song_dir: Path) -> list[dict[str, str]]:
    types = {".webm": "audio/webm; codecs=opus", ".ogg": "audio/ogg; codecs=opus",
             ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".m4a": "audio/mp4"}
    fallback_rate = {".flac": 2_000_000, ".wav": 1_500_000, ".webm": 160_000,
                     ".ogg": 160_000, ".m4a": 128_000, ".mp3": 96_000}
    candidates = []
    for suffix, mime_type in types.items():
        path = song_dir / f"audio{suffix}"
        if not path.is_file():
            continue
        bitrate, audio_only = audio_stream_quality(path)
        candidates.append((audio_only, bitrate or fallback_rate[suffix], -fallback_rate[suffix], suffix, mime_type))
    candidates.sort(reverse=True)
    return [{"src": f"audio{suffix}", "type": mime_type}
            for _audio_only, _rate, _fallback, suffix, mime_type in candidates]


def published_audio_sources(song_dir: Path) -> list[dict[str, str]]:
    """Use release-hosted media when published, with local files as a dev fallback."""
    manifest = read_packet(ROOT / "data" / "media.json") or {}
    sources = manifest.get("songs", {}).get(song_dir.name, []) if isinstance(manifest, dict) else []
    if isinstance(sources, list) and sources:
        valid = [{"src": source["src"], "type": source["type"]} for source in sources
                 if isinstance(source, dict) and source.get("src") and source.get("type")]
        if valid:
            return valid
    return listener_audio_sources(song_dir)


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
        # Older packets preserved the model evidence but accidentally rejected
        # the model's explicit `spoken_intro` / `spoken_narration` labels.
        # Rebuild the deterministic bounds from that evidence rather than
        # paying for another edge-analysis call.
        if "start" in cached and "end" in cached:
            normalized = normalize_trim_artifact(cached)
            if normalized != cached:
                write_json(target, normalized)
            return normalized
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

Crop only definite non-song material: spoken channel promotion, logo sting, advertisement, countdown, unrelated narration, post-song promotional speech, or unrelated post-song film dialogue. Preserve every musical introduction, instrumental prelude, devotional invocation, wordless vocal, intentional silence, final sung note, and natural fade.

For the start edge, boundary is the relative second where the actual song recording begins. For the end edge, boundary is the relative second through which the actual song/fade must be kept. If no crop is justified, decision must be keep and boundary must be 0 for start or {edge_length:.3f} for end. Use trim only with high confidence.

Return strict JSON only."""
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                   response_schema=edge_trim_schema(), schema_name=f"bhakti_{edge}_trim",
                                   reasoning_effort="high", max_completion_tokens=4096)
            return {"edge": edge, "clip_start": clip_start, "response": response}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, jobs))
    by_edge = {item["edge"]: item for item in results}
    allowed = {"platform_spoken", "spoken_intro", "spoken_narration", "spoken_framing", "spoken_promotion",
               "promotion", "advertisement", "logo_sting", "countdown", "unrelated_narration",
               "post_song_film_dialogue"}
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


def normalize_trim_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Recalculate trim bounds from retained edge decisions without an API call."""
    allowed = {"platform_spoken", "spoken_intro", "spoken_narration", "spoken_framing", "spoken_promotion",
               "promotion", "advertisement", "logo_sting", "countdown", "unrelated_narration",
               "post_song_film_dialogue"}
    duration = float(artifact["duration"])
    start = artifact["start"]["response"]["packet"]
    end = artifact["end"]["response"]["packet"]
    edge_length = min(75.0, duration)
    trim_start = (float(start["boundary"]) if start.get("decision") == "trim"
                  and str(start.get("confidence", "")).casefold() == "high"
                  and str(start.get("outside_type", "")).casefold() in allowed else 0.0)
    relative_end = (float(end["boundary"]) if end.get("decision") == "trim"
                    and str(end.get("confidence", "")).casefold() == "high"
                    and str(end.get("outside_type", "")).casefold() in allowed else edge_length)
    trim_end = float(artifact["end"]["clip_start"]) + relative_end
    errors = []
    if not 0 <= trim_start < trim_end <= duration or duration - (trim_end - trim_start) > min(120.0, duration * 0.2):
        errors.append("proposed edge trim is outside safety bounds")
    normalized = {**artifact, "trim_start": round(trim_start, 3), "trim_end": round(trim_end, 3),
                  "validation_errors": errors, "status": "blocked" if errors else "reviewed"}
    return normalized


def apply_lossless_trim(song_dir: Path, artifact: dict[str, Any]) -> None:
    marker = song_dir / ".transcription" / "trim-applied.json"
    existing_marker = read_packet(marker)
    if existing_marker and existing_marker.get("applied"):
        return
    if artifact.get("validation_errors"):
        raise RuntimeError("cannot apply blocked trim review")
    start, end, duration = float(artifact["trim_start"]), float(artifact["trim_end"]), float(artifact["duration"])
    if start <= 0.001 and end >= duration - 0.001:
        write_json(marker, {"applied": False, "reason": "no verified non-song edge material"})
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
    # This is an ephemeral model-timebase copy only. At 128 kb/s it remains
    # well above Gemini's internal audio resolution while keeping long inline
    # OpenRouter payloads below the provider's practical request ceiling.
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-map_metadata", "-1",
                    "-vn", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(destination)], check=True)
    source_duration = gemini.duration_seconds(source)
    normalized_duration = gemini.duration_seconds(destination)
    if abs(source_duration - normalized_duration) > 0.1:
        raise RuntimeError(f"canonical timing audio changed duration by {normalized_duration - source_duration:.3f}s")
    return destination


def normalized_transcript_audio(source: Path, destination: Path) -> Path:
    """Make one metadata-free fallback only when an audio response is empty."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-map_metadata", "-1",
                    "-vn", "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "112k", str(destination)],
                   check=True)
    if abs(gemini.duration_seconds(source) - gemini.duration_seconds(destination)) > 0.1:
        raise RuntimeError("normalized transcript audio changed source duration")
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
    song_dir: Path, source: dict[str, Any], audio: Path, options: argparse.Namespace, *,
    target_seconds: float = 300.0, minimum_core: float = 180.0,
) -> dict[str, Any]:
    segments = adaptive_audio_segments(audio, target_seconds=target_seconds, minimum_core=minimum_core)
    cache_dir = song_dir / ".transcription" / "pipeline" / "transcript-segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
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
            cache_path = cache_dir / f"segment-{segment['index']:03d}.json"
            cached = read_packet(cache_path)
            if (cached and cached.get("contract_version") == LONG_TRANSCRIPT_CONTRACT_VERSION
                    and cached.get("segment") == segment and isinstance(cached.get("response"), dict)):
                return cached
            prompt = f"""Transcribe this complete devotional-song excerpt with extreme care. Listen through the entire clip repeatedly enough to avoid missing a single sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Do not translate. Do not infer unheard text. Mark uncertainty rather than guessing.

This is segment {segment['index']} of a longer recording. Its audio covers absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; its non-overlap core is {segment['core_start']:.3f}–{segment['core_end']:.3f}. Text in the overlap is intentionally duplicated and must still be transcribed. Identify the language and native script per line, including code-switching.

Source metadata is only a lead, never proof:
{json.dumps(source, ensure_ascii=False)}

Return strict JSON:
{{"lines":[{{"id":"segment-{segment['index']}-line-000","source_text":"","roman":"","language":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","partial":"none|leading|trailing","notes":""}}],"performance_order":[{{"line_id":"","occurrence":1}}],"uncertainties":[]}}"""
            response = None
            for attempt in range(2):
                try:
                    response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                           response_schema=segment_transcript_schema(), schema_name="bhakti_segment_transcript",
                                           reasoning_effort="high", max_completion_tokens=32768)
                    break
                except RuntimeError as exc:
                    if attempt or "required JSON packet" not in str(exc):
                        raise
            if response is None:
                raise RuntimeError(f"segment {segment['index']} produced no transcription response")
            item = {"contract_version": LONG_TRANSCRIPT_CONTRACT_VERSION,
                    "segment": segment, "response": response}
            write_json(cache_path, item)
            return item

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
    try:
        result = ask(prompt, audio, options)
    except RuntimeError as exc:
        # A few provider responses are empty for otherwise valid M4A/MP3
        # input. Retry once with a clean audio-only MP3; this does not change
        # the preserved listener master or create another open-ended retry.
        if "required JSON packet" not in str(exc):
            raise
        with tempfile.TemporaryDirectory(prefix="bhakti-transcript-retry-") as temporary:
            fallback = normalized_transcript_audio(audio, Path(temporary) / "transcript.mp3")
            try:
                result = ask(prompt, fallback, options)
            except RuntimeError as fallback_exc:
                if "required JSON packet" not in str(fallback_exc) or gemini.duration_seconds(audio) <= 180:
                    raise
                # A second empty provider body is a transport failure, not
                # lyric evidence. Divide only this recording into bounded
                # overlapping excerpts and reconcile them deterministically.
                result = transcribe_long_audio(song_dir, source, audio, options, target_seconds=150.0)
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
    # Adjacent long-recording audits can legitimately choose different Indic
    # scripts for the same audible line.  The reviewed romanization is the
    # shared comparison surface; using source_text first made Urdu and
    # Devanagari copies of one line look unrelated and produced false seam
    # failures plus corrupt coarse timing hints.
    value = str(line.get("roman") or line.get("source_text") or "").casefold()
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
            # A segment boundary can split a model's over-long line into two
            # complete source units.  When its opening units are exactly the
            # suffix of the preceding segment, they are overlapping evidence,
            # not a new performance.  This avoids a low fuzzy score merely
            # because the left line also contains the preceding unit.
            if left_text.endswith(right_text):
                score = 1.0
            else:
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
            "kannada": "Kannada", "bra": "Braj", "braj": "Braj", "raj": "Rajasthani",
            "rajasthani": "Rajasthani"}.get(key, value.strip())


def merge_audited_segments(audited_segments: list[dict[str, Any]]) -> dict[str, Any]:
    merged: list[dict[str, Any]] = []
    seam_matches: list[dict[str, int]] = []
    languages: list[str] = []
    uncertainties: list[str] = []
    for index, item in enumerate(audited_segments):
        packet = item["audit"]["packet"]
        raw_current = ordered_segment_lines(packet)
        current = raw_current
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
            # A complete lyric line at a segment edge may be marked
            # ``trailing`` in the preceding clip and therefore omitted from
            # ``merged`` to avoid duplication.  It is still decisive evidence
            # that the following segment begins at the same performance.  Use
            # raw adjoining packets for seam confidence, but retain the
            # trimmed lists for public occurrence deduplication.
            previous_raw = ordered_segment_lines(audited_segments[index - 1]["audit"]["packet"])
            _raw_left, _raw_right, raw_score = balanced_overlap(previous_raw, raw_current)
            score = max(score, raw_score)
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


def reconcile_segment_seam_uncertainties(
    audited_segments: list[dict[str, Any]], uncertainties: list[str]
) -> list[str]:
    """Re-evaluate only deterministic seam confidence for a cached audit.

    This deliberately preserves its reviewed surface and performance order.
    It is safe for a historical packet because script-normalized overlap can
    resolve a false seam warning without rewriting any text or timing.
    """
    retained = [str(value) for value in uncertainties
                if not str(value).startswith("segment seam ")]
    for index in range(1, len(audited_segments)):
        previous = ordered_segment_lines(audited_segments[index - 1]["audit"]["packet"])
        current = ordered_segment_lines(audited_segments[index]["audit"]["packet"])
        _left, _right, score = balanced_overlap(previous, current)
        if score < 0.8:
            retained.append(f"segment seam {index - 1}/{index} overlap score is only {score:.3f}")
    return retained


def audit_long_transcript(
    song_dir: Path, raw: dict[str, Any], audio: Path, options: argparse.Namespace
) -> dict[str, Any]:
    segments = raw["packet"]["segments"]
    witness = source_witness.acquire(song_dir, song_dir.name)
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
            # A source-witness audit is specifically a new audio pass with
            # witness excerpts. Reusing a prior non-witness segment would
            # falsely report that verification happened.
            if cached and not options.source_witness_audit:
                return cached
            witness_context = source_witness.prompt_context(witness, first.get("lines", []))
            prompt = f"""This is the required second transcription pass for one segment of a long devotional recording. Audit the entire first-pass transcript below against the complete attached segment. Use the first transcript as your working draft; do not start over.

Be extremely careful not to miss, hallucinate, reorder, or silently correct any sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Preserve overlap text because local code reconciles it. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation. Do not translate or estimate timestamps. Mark genuine uncertainty rather than guessing.

Segment audio: absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; core {segment['core_start']:.3f}–{segment['core_end']:.3f}.

FIRST TRANSCRIPT:
{json.dumps(first, ensure_ascii=False)}
{witness_context}

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
            "source_witness": witness.get("witness") if witness else None,
            "merge_contract_version": LONG_MERGE_VERSION, "resolved_model": options.model}


def audit_transcript(song_dir: Path, raw: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "02-transcript-audit.json"
    existing = read_packet(target)
    if existing and not options.force and not options.source_witness_audit:
        if existing.get("segment_audits") and existing.get("merge_contract_version") != LONG_MERGE_VERSION:
            existing["packet"] = merge_audited_segments(existing["segment_audits"])
            existing["merge_contract_version"] = LONG_MERGE_VERSION
            existing["merge_contract_rebuilt"] = True
            write_json(target, existing)
        elif existing.get("segment_audits"):
            packet = existing.get("packet", {})
            if isinstance(packet, dict):
                reconciled = reconcile_segment_seam_uncertainties(
                    existing["segment_audits"], list(packet.get("uncertainties", []))
                )
                if reconciled != packet.get("uncertainties", []):
                    packet["uncertainties"] = reconciled
                    write_json(target, existing)
        return existing
    if raw.get("packet", {}).get("segmented"):
        result = audit_long_transcript(song_dir, raw, audio, options)
        write_json(target, result)
        source_witness.write_comparison_report(song_dir, song_dir.name, result)
        return result
    witness = source_witness.acquire(song_dir, song_dir.name)
    witness_context = source_witness.prompt_context(witness, raw.get("packet", {}).get("lines", []))
    prompt = f"""This is the required second transcription pass. Audit the entire first-pass transcript below against the complete attached devotional recording from beginning to end. Use the first transcript as your explicit working draft; do not start from an empty guess. This is transcription verification, not timing or translation.

Be extremely careful: correct every missed, hallucinated, duplicated, reordered, or misheard lyric. Preserve every audible performance occurrence in exact order, including lead pickups before answers and later returns. When the draft came from overlapping segments, reconcile duplicate overlap evidence without deleting genuine repeated performances. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation; do not mix plain and scholarly spellings. Do not translate or estimate timestamps. If any content remains unclear, put it in uncertainties; do not silently guess.

Candidate transcript:
{json.dumps(raw['packet'], ensure_ascii=False)}
{witness_context}

Return strict JSON:
{{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"verified_lines":[{{"id":"stable-kebab-id","source_text":"","roman":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"stable-kebab-id","occurrence":1,"notes":""}}],"changes":[],"uncertainties":[]}}"""
    try:
        result = gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=options.timeout,
                             response_schema=audited_transcript_schema(), schema_name="bhakti_audited_transcript",
                             reasoning_effort="high", max_completion_tokens=65536)
    except RuntimeError as exc:
        if "required JSON packet" not in str(exc):
            raise
        with tempfile.TemporaryDirectory(prefix="bhakti-audit-retry-") as temporary:
            fallback = normalized_transcript_audio(audio, Path(temporary) / "audit.mp3")
            try:
                result = gemini.call(options.model, gemini.key(), prompt, audio=fallback, timeout=options.timeout,
                                     response_schema=audited_transcript_schema(), schema_name="bhakti_audited_transcript",
                                     reasoning_effort="high", max_completion_tokens=65536)
            except RuntimeError as fallback_exc:
                if "required JSON packet" not in str(fallback_exc) or gemini.duration_seconds(audio) <= 180:
                    raise
                # Last-resort recovery for a provider that rejects this
                # recording's full-audio audit: independent short audio
                # witnesses plus deterministic overlap reconciliation.
                source = read_packet(song_dir / ".transcription" / "source.json") or {}
                segmented_raw = transcribe_long_audio(song_dir, source=source, audio=audio, options=options,
                                                       target_seconds=150.0, minimum_core=90.0)
                result = audit_long_transcript(song_dir, segmented_raw, audio, options)
    write_json(target, result)
    if witness:
        result["source_witness"] = witness.get("witness")
        write_json(target, result)
        source_witness.write_comparison_report(song_dir, song_dir.name, result)
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


def compress_adjacent_reader_entries(
    sequence: list[dict[str, Any]], timings: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Merge adjacent identical displayed entries into one repeat-counted block."""
    if len(sequence) != len(timings):
        raise RuntimeError("sequence/timing arrays differ in length")
    merged_sequence: list[dict[str, Any]] = []
    merged_timings: list[dict[str, Any]] = []
    merged_boundaries = 0
    for entry, timing in zip(sequence, timings):
        ref = entry["ref"]
        section = entry.get("section", "verse")
        repeats = int(entry.get("repeats", 1) or 1)
        start = round(float(timing["start"]), 3)
        end = round(float(timing["end"]), 3)
        if merged_sequence and merged_sequence[-1]["ref"] == ref and merged_sequence[-1]["section"] == section:
            merged_sequence[-1]["repeats"] += repeats
            merged_timings[-1]["end"] = end
            merged_boundaries += 1
            continue
        merged_sequence.append({"ref": ref, "section": section, "repeats": repeats})
        merged_timings.append({"start": start, "end": end})
    return merged_sequence, merged_timings, merged_boundaries


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
    compressed: list[tuple[dict[str, Any], float, int]] = []
    previous_signature = None
    for line, point, segment_index in merged:
        signature = lyric_signature(line)
        if signature == previous_signature:
            continue
        compressed.append((line, point, segment_index))
        previous_signature = signature
    starts: list[float] = []
    for _line, point, _segment_index in compressed:
        starts.append(round(min(duration, max(point, starts[-1] + 0.1 if starts else 0.0)), 3))
    rebuilt = [{"line": line, "start": starts[index], "segment_index": segment_index}
               for index, (line, _point, segment_index) in enumerate(compressed)]
    pairs = align_long_coarse_entries(occurrences, rebuilt)
    matched_actual = {actual_index for actual_index, _coarse_index in pairs}
    matched_coarse = {coarse_index for _actual_index, coarse_index in pairs}
    if len(matched_coarse) != len(rebuilt):
        raise RuntimeError(
            "long-audio coarse reconciliation leaves "
            f"{len(rebuilt) - len(matched_coarse)} rebuilt occurrences unmatched"
        )

    coarse_by_actual = {actual_index: coarse_index for actual_index, coarse_index in pairs}
    result: list[dict[str, Any]] = []
    for index, occurrence in enumerate(occurrences):
        coarse_index = coarse_by_actual.get(index)
        routing_only = coarse_index is None
        if routing_only:
            preceding = next((left for left in range(index - 1, -1, -1)
                              if left in coarse_by_actual), None)
            following = next((right for right in range(index + 1, len(occurrences))
                              if right in coarse_by_actual), None)
            if preceding is None or following is None:
                raise RuntimeError("long-audio coarse reconciliation cannot bracket an unmatched occurrence")
            left = rebuilt[coarse_by_actual[preceding]]
            right = rebuilt[coarse_by_actual[following]]
            if right["start"] <= left["start"]:
                raise RuntimeError("long-audio coarse reconciliation has non-increasing matched anchors")
            position = (index - preceding) / (following - preceding)
            start = round(float(left["start"]) + (float(right["start"]) - float(left["start"])) * position, 3)
            # The following segment owns a cross-segment gap and its clip
            # includes the intentional overlap; otherwise retain the known
            # parent segment.  This hint is routing-only, never timing proof.
            segment_index = (right if left["segment_index"] != right["segment_index"] else left)["segment_index"]
        else:
            entry = rebuilt[coarse_index]
            start = float(entry["start"])
            segment_index = entry["segment_index"]
        result.append({"occurrence_id": occurrence["occurrence_id"], "ref": occurrence["ref"],
                       "section": occurrence["section"], "repeats": occurrence["repeats"],
                       "start": start, "segment_index": segment_index,
                       "routing_only": routing_only})
    for index, entry in enumerate(result):
        entry["end"] = result[index + 1]["start"] if index + 1 < len(result) else duration
    return result


def coarse_match_similarity(actual: dict[str, Any], rebuilt: dict[str, Any]) -> float | None:
    """Return a conservative, script-independent coarse-routing match score."""
    left = lyric_signature(actual)
    right = lyric_signature(rebuilt.get("line", rebuilt))
    if not left or not right:
        return None
    if left == right:
        return 1.0
    if min(len(left), len(right)) < 12:
        return None
    score = difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()
    return score if score >= 0.82 else None


def align_long_coarse_entries(
    occurrences: list[dict[str, Any]], rebuilt: list[dict[str, Any]]
) -> list[tuple[int, int]]:
    """Align rebuilt coarse cues to a retained reviewed display order.

    This is intentionally a routing alignment, not a timing alignment.  It
    matches all rebuilt cues in order and leaves only retained-only display
    occurrences for bracketed interpolation.  Exact romanized signatures are
    preferred; conservative fuzzy matches tolerate audited vowel/nasal
    transliteration differences at script-switch seams.
    """
    count_actual, count_rebuilt = len(occurrences), len(rebuilt)
    # Values rank match count first, then lexical similarity, then fewer gaps.
    table = [[(0, 0, 0) for _ in range(count_rebuilt + 1)] for _ in range(count_actual + 1)]
    for actual_index in range(count_actual - 1, -1, -1):
        for rebuilt_index in range(count_rebuilt - 1, -1, -1):
            skip_actual = table[actual_index + 1][rebuilt_index]
            skip_actual = (skip_actual[0], skip_actual[1], skip_actual[2] - 1)
            skip_rebuilt = table[actual_index][rebuilt_index + 1]
            skip_rebuilt = (skip_rebuilt[0], skip_rebuilt[1], skip_rebuilt[2] - 1)
            best = max(skip_actual, skip_rebuilt)
            similarity = coarse_match_similarity(occurrences[actual_index], rebuilt[rebuilt_index])
            if similarity is not None:
                following = table[actual_index + 1][rebuilt_index + 1]
                matched = (following[0] + 1, following[1] + round(similarity * 1_000_000), following[2])
                best = max(best, matched)
            table[actual_index][rebuilt_index] = best

    pairs: list[tuple[int, int]] = []
    actual_index = rebuilt_index = 0
    while actual_index < count_actual and rebuilt_index < count_rebuilt:
        similarity = coarse_match_similarity(occurrences[actual_index], rebuilt[rebuilt_index])
        if similarity is not None:
            following = table[actual_index + 1][rebuilt_index + 1]
            matched = (following[0] + 1, following[1] + round(similarity * 1_000_000), following[2])
            if matched == table[actual_index][rebuilt_index]:
                pairs.append((actual_index, rebuilt_index))
                actual_index += 1
                rebuilt_index += 1
                continue
        if table[actual_index + 1][rebuilt_index] >= table[actual_index][rebuilt_index + 1]:
            actual_index += 1
        else:
            rebuilt_index += 1
    return pairs


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
        # `:batch` is only a transport choice. Audio requests always use the
        # same synchronous base model, so fast/economy runs share evidence.
        "model": gemini.batch_base_model(options.model),
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
            if index >= len(targets) or raw["occurrence_id"] != targets[index]["occurrence_id"]:
                raise ValueError
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


def build_long_timing_subchunks(
    parent: dict[str, Any], occurrences: list[dict[str, Any]], coarse_sequence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Split a parent segment while keeping interpolated hints broad.

    A routing-only hint exists solely to place an occurrence in a bounded
    audio region.  It may never constrain a measured onset to its interpolated
    second, so any child containing one receives the full parent clip.
    """
    children = []
    indices = parent["target_indices"]
    for child_index, offset in enumerate(range(0, len(indices), 10)):
        child_indices = indices[offset:offset + 10]
        first, last = child_indices[0], child_indices[-1]
        first_coarse = float(coarse_sequence[first]["start"])
        last_coarse = float(coarse_sequence[last]["start"])
        routing_only = any(bool(coarse_sequence[index].get("routing_only")) for index in child_indices)
        children.append({
            "index": int(parent["index"]) * 100 + child_index,
            "parent_segment_index": int(parent["index"]),
            "grid": "long-segment-routing" if routing_only else "long-segment-window",
            "core_start": first_coarse,
            "core_end": last_coarse,
            "clip_start": float(parent["clip_start"]) if routing_only else max(float(parent["clip_start"]), first_coarse - 20.0),
            "clip_end": float(parent["clip_end"]) if routing_only else min(float(parent["clip_end"]), last_coarse + 20.0),
            "routing_only": routing_only,
            "target_indices": child_indices,
            "target_occurrences": [
                {**occurrences[index], "coarse_source_start": coarse_sequence[index]["start"]}
                for index in child_indices
            ],
            "preceding_context": occurrences[first - 1] if first else None,
            "following_context": occurrences[last + 1] if last + 1 < len(occurrences) else None,
        })
    return children


def align_long_segments(
    song_dir: Path, audio: Path, audited: dict[str, Any], occurrences: list[dict[str, Any]],
    coarse_sequence: list[dict[str, Any]], duration: float, options: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Align long recordings in bounded lyric-aware windows.

    Valid historical segment caches remain reusable. Fresh or failed 4–6 minute
    segment packets are divided into at most ten exact audited occurrences per
    request, with overlap around their deterministic coarse positions. This
    keeps the model's job to onset lookup rather than long-range bookkeeping.
    """
    chunks = build_long_timing_chunks(audited, occurrences, coarse_sequence, duration)
    cache_dir = song_dir / ".transcription" / "pipeline" / "long-timing-segments"
    cache_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bhakti-long-timing-") as temporary:
        destination = Path(temporary)
        retained_reports: list[dict[str, Any]] = []
        work: list[tuple[dict[str, Any], Path]] = []
        for chunk in chunks:
            parent_path = cache_dir / f"segment-{chunk['index']:03d}.json"
            cached = read_packet(parent_path)
            if cached:
                parent_report = refine_timing_chunk(
                    audio, occurrences, chunk, options, destination, parent_path,
                    max_coarse_delta=max(90.0, chunk["clip_end"] - chunk["clip_start"]),
                    reasoning_effort="high", max_completion_tokens=65536,
                )
                # A malformed or uncertain sibling must not discard exact,
                # independently valid starts in this same bounded window.
                # The unresolved occurrences receive narrow two-pass recovery
                # below; the valid ones remain evidence rather than causing a
                # costly re-timing cascade across the whole long recording.
                retained_reports.append(parent_report)
                continue
            for child_index, child in enumerate(build_long_timing_subchunks(chunk, occurrences, coarse_sequence)):
                work.append((child, cache_dir / f"segment-{chunk['index']:03d}-window-{child_index:02d}.json"))

        def align_window(item: tuple[dict[str, Any], Path]) -> dict[str, Any]:
            child, path = item
            coarse_guard = (float(child["clip_end"]) - float(child["clip_start"])
                            if child.get("routing_only")
                            else max(30.0, float(child["clip_end"]) - float(child["clip_start"])))
            return refine_timing_chunk(
                audio, occurrences, child, options, destination, path,
                max_coarse_delta=coarse_guard,
                reasoning_effort="high", max_completion_tokens=32768,
            )

        if work:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(work))) as pool:
                window_reports = list(pool.map(align_window, work))
        else:
            window_reports = []
        for report in window_reports:
            retained_reports.append(report)
        reports = retained_reports
    starts_by_id: dict[str, float] = {}
    missing: list[int] = []
    for report in reports:
        uncertain = set(str(value) for value in report.get("uncertain_ids", []))
        for entry in report["starts"]:
            if entry["occurrence_id"] in uncertain:
                continue
            if entry["occurrence_id"] in starts_by_id:
                continue
            starts_by_id[entry["occurrence_id"]] = float(entry["start"])
    for index, occurrence in enumerate(occurrences):
        if occurrence["occurrence_id"] not in starts_by_id:
            missing.append(index)
    recoveries: list[dict[str, Any]] = []
    if missing:
        with tempfile.TemporaryDirectory(prefix="bhakti-long-single-starts-") as temporary:
            destination = Path(temporary)
            def recover(index: int) -> dict[str, Any]:
                occurrence_id = occurrences[index]["occurrence_id"]
                prior = next((starts_by_id.get(occurrences[left]["occurrence_id"])
                              for left in range(index - 1, -1, -1)
                              if starts_by_id.get(occurrences[left]["occurrence_id"]) is not None), 0.0)
                following = next((starts_by_id.get(occurrences[right]["occurrence_id"])
                                  for right in range(index + 1, len(occurrences))
                                  if starts_by_id.get(occurrences[right]["occurrence_id"]) is not None), duration)
                candidates = [starts_by_id[occurrence_id]] if occurrence_id in starts_by_id else []
                candidates.append(max(float(prior) + 0.01, min(float(coarse_sequence[index]["start"]), float(following) - 0.01)))
                return refine_single_start(audio, occurrences, index, candidates, duration, options, destination,
                                           lower_bound=float(prior), upper_bound=float(following))
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
                recoveries = list(pool.map(recover, missing))
        for report in recoveries:
            if not report["validation_errors"]:
                starts_by_id[report["occurrence_id"]] = float(report["start"])
    # A repeated refrain can make a locally perfect narrow response land on
    # the earlier occurrence. Check it against already accepted neighbours and
    # make bounded, order-aware recoveries rather than publishing a shifted
    # sequence or restarting every timing window. A first correction can make
    # the following identical refrain newly out of order, so iterate a small
    # number of times over the affected local run.
    order_repairs: list[dict[str, Any]] = []
    for _round in range(3):
        violations: list[int] = []
        previous = -1.0
        for index, occurrence in enumerate(occurrences):
            value = starts_by_id.get(occurrence["occurrence_id"])
            if value is not None and value <= previous:
                violations.append(index)
            elif value is not None:
                previous = value
        if not violations:
            break
        with tempfile.TemporaryDirectory(prefix="bhakti-order-aware-starts-") as temporary:
            destination = Path(temporary)
            def recover_order(index: int) -> dict[str, Any]:
                prior = starts_by_id.get(occurrences[index - 1]["occurrence_id"], 0.0) if index else 0.0
                following = next((starts_by_id.get(occurrences[right]["occurrence_id"])
                                  for right in range(index + 1, len(occurrences))
                                  if (starts_by_id.get(occurrences[right]["occurrence_id"]) is not None
                                      and float(starts_by_id[occurrences[right]["occurrence_id"]]) > float(prior) + 0.01)), duration)
                candidate = max(prior + 0.5, min(float(coarse_sequence[index]["start"]), float(following) - 0.5))
                return refine_single_start(
                    audio, occurrences, index, [candidate], duration, options, destination,
                    lower_bound=float(prior), upper_bound=float(following),
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(violations))) as pool:
                order_repairs = list(pool.map(recover_order, violations))
        for report in order_repairs:
            if not report["validation_errors"]:
                starts_by_id[report["occurrence_id"]] = float(report["start"])
    errors = [f"{report['occurrence_id']}: {error}" for report in recoveries for error in report["validation_errors"]]
    errors.extend(f"{report['occurrence_id']}: {error}" for report in order_repairs for error in report["validation_errors"])
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
    return sequence, reports + recoveries + order_repairs, errors


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


def corroborated_by_existing(point: float, measurements: list[float], tolerance: float = 0.75) -> bool:
    """Whether a new independent onset agrees with any evidence already paid for."""
    return any(abs(point - existing) <= tolerance for existing in measurements)


def refine_single_start(
    audio: Path, occurrences: list[dict[str, Any]], index: int, candidate_measurements: list[float],
    duration: float, options: argparse.Namespace, destination: Path, *, clip_radius: float = 20.0,
    lower_bound: float | None = None, upper_bound: float | None = None,
) -> dict[str, Any]:
    target = occurrences[index]
    candidate = median(candidate_measurements)
    if lower_bound is not None and upper_bound is not None and upper_bound > lower_bound:
        clip_start, clip_end = max(0.0, lower_bound - 6.0), min(duration, upper_bound + 6.0)
    else:
        clip_start, clip_end = max(0.0, candidate - clip_radius), min(duration, candidate + clip_radius)
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
    for attempt in range(2):
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
            # The coarse long-segment route is deliberately only a routing
            # hint. A pair of tightly agreeing lyric-aware measurements may
            # legitimately expose a several-second systematic coarse offset;
            # permit that pair to win, while retaining a hard 12-second guard
            # against drifting into a different repeated occurrence.
            if not clip_start <= point <= clip_end or (lower_bound is None and abs(point - candidate) > 12.0):
                errors.append("single start is outside the candidate clip")
            if lower_bound is not None and upper_bound is not None and not lower_bound < point < upper_bound:
                errors.append("single start is outside the accepted-neighbour bracket")
            if any(marker in uncertainty for marker in ("not_in_clip", "not in clip", "not present", "not heard", "unable", "cannot locate")):
                errors.append("single start is not locatable")
            attempts.append({"attempt": attempt + 1, "start": round(point, 3), "uncertainty_note": uncertainty,
                             "response": response, "validation_errors": errors})
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            attempts.append({"attempt": attempt + 1, "error": str(exc), "validation_errors": ["unusable single response"]})
        valid = [item for item in attempts if not item["validation_errors"]]
        if valid and corroborated_by_existing(valid[-1]["start"], candidate_measurements):
            break
        if len(valid) >= 2 and max(item["start"] for item in valid) - min(item["start"] for item in valid) <= 0.5:
            break
    valid = [item for item in attempts if not item["validation_errors"]]
    errors: list[str] = []
    corroborated = [item for item in valid if corroborated_by_existing(item["start"], candidate_measurements)]
    if corroborated:
        point = corroborated[-1]["start"]
    elif len(valid) >= 2:
        values = [item["start"] for item in valid]
        point = median(values)
        if max(values) - min(values) > 0.5:
            errors.append("single-start measurements do not agree")
    else:
        point = candidate
        errors.append("single start lacks agreeing evidence")
    return {"kind": "single", "occurrence_id": target["occurrence_id"],
            "candidate": candidate, "candidate_measurements": candidate_measurements,
            "start": round(point, 3), "attempts": attempts, "validation_errors": errors}



def refine_all_starts(
    audio: Path,
    occurrences: list[dict[str, Any]],
    coarse_sequence: list[dict[str, Any]],
    duration: float,
    options: argparse.Namespace,
    cache_dir: Path | None = None,
    *,
    coarse_is_evidence: bool = True,
    max_coarse_delta: float = 20.0,
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
                    max_coarse_delta=max_coarse_delta,
                ),
                chunks,
            ))

    # A model-produced full-track start is independent timing evidence. A
    # deterministic fallback grid is only a routing hint and must never vote in
    # onset consensus or reject an accurate clip-relative measurement.
    measurements: dict[str, list[float]] = {
        occurrence["occurrence_id"]: ([float(coarse_sequence[index]["start"])]
                                       if coarse_is_evidence else [])
        for index, occurrence in enumerate(occurrences)
    }
    for report in reports:
        # One malformed onset must not erase every valid onset returned in the
        # same structured window.
        for entry in report["starts"]:
            measurements[entry["occurrence_id"]].append(entry["start"])
    unresolved = [index for index, occurrence in enumerate(occurrences)
                  if consensus_value(measurements[occurrence["occurrence_id"]], tolerance=0.75) is None]

    dispute_reports: list[dict[str, Any]] = []
    if unresolved:
        grouped: dict[int, list[int]] = {}
        for index in unresolved:
            values = measurements[occurrences[index]["occurrence_id"]]
            routing_point = median(values) if values else float(coarse_sequence[index]["start"])
            grouped.setdefault(int(routing_point // 120.0), []).append(index)
        dispute_chunks = []
        for group, indices in sorted(grouped.items()):
            core_start, core_end = group * 120.0, min(duration, (group + 1) * 120.0)
            first, last = indices[0], indices[-1]
            span_indices = list(range(first, last + 1))
            dispute_chunks.append({
                "index": group,
                "grid": "dispute-verification",
                "core_start": core_start,
                "core_end": core_end,
                "clip_start": max(0.0, core_start - 15.0),
                "clip_end": min(duration, core_end + 15.0),
                "target_indices": span_indices,
                "target_occurrences": [
                    {**occurrences[index],
                     "coarse_source_start": (
                         median(measurements[occurrences[index]["occurrence_id"]])
                         if measurements[occurrences[index]["occurrence_id"]]
                         else float(coarse_sequence[index]["start"])
                     )}
                    for index in span_indices
                ],
                "preceding_context": occurrences[first - 1] if first else None,
                "following_context": occurrences[last + 1] if last + 1 < len(occurrences) else None,
            })
        with tempfile.TemporaryDirectory(prefix="bhakti-dispute-windows-") as temporary:
            destination = Path(temporary)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(dispute_chunks))) as pool:
                dispute_reports = list(pool.map(
                    lambda chunk: refine_timing_chunk(
                        audio, occurrences, chunk, options, destination,
                        cache_dir / f"dispute-{chunk['index']:03d}.json" if cache_dir else None,
                        max_coarse_delta=max_coarse_delta,
                    ),
                    dispute_chunks,
                ))
        for report in dispute_reports:
            for entry in report["starts"]:
                measurements[entry["occurrence_id"]].append(entry["start"])
        unresolved = [index for index, occurrence in enumerate(occurrences)
                      if consensus_value(measurements[occurrence["occurrence_id"]], tolerance=0.75) is None]

    recoveries: list[dict[str, Any]] = []
    if len(unresolved) > max(5, len(occurrences) // 5):
        errors = [f"verification disagrees for {len(unresolved)} of {len(occurrences)} occurrences; "
                  "refusing a per-line retry cascade"]
        evidence = reports + dispute_reports + [{"kind": "consensus", "starts": [
            {"occurrence_id": occurrence["occurrence_id"],
             "measurements": measurements[occurrence["occurrence_id"]], "start": None}
            for occurrence in occurrences], "validation_errors": errors}]
        return [], evidence, errors
    if unresolved:
        with tempfile.TemporaryDirectory(prefix="bhakti-single-starts-") as temporary:
            destination = Path(temporary)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(unresolved))) as pool:
                recoveries = list(pool.map(
                    lambda index: refine_single_start(
                                                      audio, occurrences, index,
                                                      measurements[occurrences[index]["occurrence_id"]],
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
    evidence = reports + dispute_reports + recoveries + [{"kind": "consensus", "starts": consensus, "validation_errors": []}]
    return sequence, evidence, errors

def uniform_coarse_sequence(occurrences: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """Provide a deterministic fallback when the full-song absolute pass fails."""
    if not occurrences:
        return []
    step = duration / max(1, len(occurrences))
    return [
        {
            "occurrence_id": occurrence["occurrence_id"],
            "ref": occurrence["ref"],
            "section": occurrence["section"],
            "repeats": occurrence["repeats"],
            "start": round(min(duration, (index + 0.5) * step), 3),
        }
        for index, occurrence in enumerate(occurrences)
    ]

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
            # Google rejects a very large JSON Schema for long/repetitive
            # recordings before it considers the audio. The prompt still
            # requires the identical ordered JSON object; local validation
            # remains authoritative, while later bounded windows use strict
            # per-window schemas.
            coarse_schema = start_only_timing_schema(len(occurrences)) if len(occurrences) <= 40 else None
            response = gemini.call(options.model, gemini.key(), prompt, audio=model_audio, timeout=options.timeout,
                                   response_schema=coarse_schema,
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
        elif not audited.get("segment_audits"):
            fallback_coarse_sequence = uniform_coarse_sequence(occurrences, duration)
            sequence, refinements, refinement_errors = refine_all_starts(
                model_audio, occurrences, fallback_coarse_sequence, duration, options,
                song_dir / ".transcription" / "pipeline" / "timing-windows",
                coarse_is_evidence=False,
                max_coarse_delta=duration,
            )
            if not refinement_errors:
                coarse_sequence = fallback_coarse_sequence
                errors = []
                uncertain = []
            else:
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
    registry = preserved_term_registry().get("terms", {})
    for line in lines:
        line_id = line.get("id", "<unknown>")
        frame = gloss_by_id.get(line_id, {}).get("semantic_frame")
        if not isinstance(frame, dict) or any(not isinstance(frame.get(field), str) for field in SEMANTIC_FRAME_FIELDS):
            errors.append(f"{line_id} lacks a complete semantic frame")
        for word_index, word in enumerate(gloss_by_id.get(line_id, {}).get("word_glosses", [])):
            concept_key = word.get("concept_key")
            preserve = word.get("preserve_in_english")
            if not isinstance(concept_key, str) or not isinstance(preserve, bool):
                errors.append(f"{line_id} word gloss {word_index} lacks concept preservation fields")
            elif concept_key and concept_key not in registry:
                errors.append(f"{line_id} word gloss {word_index} uses unknown concept key {concept_key!r}")
            elif preserve and not concept_key:
                errors.append(f"{line_id} word gloss {word_index} preserves an uncurated concept")
            if gloss_policy.is_self_referential(word.get("roman", ""), word.get("gloss", "")):
                errors.append(f"{line_id} word gloss {word_index} repeats the visible term instead of explaining it")
    return errors


def clean_gloss_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for row in rows:
        value = dict(row)
        value["word_glosses"] = [gloss_policy.clean_word(word) for word in row.get("word_glosses", [])
                                 if any(character.isalnum() for character in str(word.get("roman", "")))]
        cleaned.append(value)
    return cleaned


def normalize_gloss_rows(lines: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    line_by_id = {line.get("id"): line for line in lines}
    normalized = []
    for row in rows:
        value = dict(row)
        words = [dict(word) for word in row.get("word_glosses", [])
                 if any(character.isalnum() for character in str(word.get("roman", "")))]
        expected = [token for token in str(line_by_id.get(row.get("id"), {}).get("roman", "")).split()
                    if any(character.isalnum() for character in token)]
        if len(words) == len(expected):
            for index, token in enumerate(expected):
                words[index]["roman"] = token
        value["word_glosses"] = [gloss_policy.clean_word(word) for word in words]
        normalized.append(value)
    return normalized


def gloss(song_dir: Path, audited: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "04-glosses.json"
    lines = audited["packet"].get("verified_lines", [])
    existing = read_packet(target)
    if existing and isinstance(existing.get("packet", {}).get("glosses"), list):
        existing["packet"]["glosses"] = normalize_gloss_rows(lines, existing["packet"]["glosses"])
    if (existing and not options.force and existing.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
            and not gloss_contract_errors(lines, existing.get("packet", {}).get("glosses", []))):
        return existing
    def prompt_for(batch: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
        term_registry = preserved_term_registry()
        return f"""Create a literal word-by-word reading of the TARGET audited devotional lyrics. Work line by line and use the surrounding song context.

Create exactly one word_gloss entry for each lexical whitespace-delimited surface token in the supplied roman line, in the identical order. Omit a token made entirely of punctuation, such as `।`, `॥`, a dash, or an ellipsis; punctuation remains visible but is not a word or hover target. The `roman` value must copy that complete displayed lexical token exactly; never split sandhi or a written compound into separate entries, and never substitute an underlying dictionary form. Give the contextually correct primary sense first. A gloss is semantic evidence, not an English draft: do not bake a clumsy phrase such as “cast a glance of mercy” into a token gloss when the phrase-level meaning is “look upon someone with mercy.” Put phrase meaning and idiom in the semantic frame instead. Use established English words or transparent source-supported compounds. Never present a franchise-specific fictional coinage such as `adamantium`, `vibranium`, or `mithril` as ordinary English. Rare but attested English such as `adamantine` is valid when it is the precise supported sense.

Before any later translation, explicitly reconstruct the semantic frame: who is acting or experiencing; the action or state; its patient or complement; modifiers; negation or modality; the exact literal image and agency; any established idiom; and how the line connects grammatically to its neighbors. Preserve personification and unusual agency rather than normalizing them. Distinguish a suffered or resultant state from a self-caused act: if the line says the speaker is broken, undone, struck, or seized, do not reinterpret it as the speaker actively breaking, undoing, striking, or seizing themself. Do not replace one metaphor with another: if a feeling “takes hold,” do not relabel it as kindling or stirring. Preserve a spatial word directly—“inside” remains “inside”—rather than upgrading it to “deep within” unless the source actually expresses depth. Represent reduplication as emphasis or repetition without inventing a new image. Expand relational objects when English requires their complement—a hem is the hem of a garment. Distinguish culturally specific objects precisely, such as an alms bag rather than a generic satchel, and palm/open palm rather than an abstract “hand” when the source requires it. For `raham nazar`, record the phrase-level meaning “look upon someone with mercy,” never “cast a glance.”

Explain internal morphemes inside the token's `gloss` or `grammar_note`. Give a short grammar note for ellipsis, agreement, sandhi, compounds, or syntax. Choose the contextually supported sense of a polysemous word; do not call ordinary dictionary polysemy uncertain. Use uncertainty only when the audited lyric itself remains genuinely unresolved. Do not write a fluent English sentence in this stage.

Only terms in the CURATED PRESERVED-TERM REGISTRY may remain in IAST in English. For a matching term, set `concept_key`, set `preserve_in_english=true`, use the canonical IAST form later, and write a short context-specific hover gloss rather than a flattening synonym. The hover must contain the meaning only: never repeat the visible Roman term before its explanation. Write `intellect; faculty of discernment`, not `buddhi (intellect; faculty of discernment)`; write `spiritual teacher`, not `guru / spiritual teacher`. For a proper name or divine title, explain its identity or role rather than merely spelling the same name again. Build a local glossary while processing this song: when the same displayed token recurs in the same grammatical and devotional role, reuse its most specific established explanation verbatim. A changed explanation is allowed only when the local syntax or imagery materially changes; say why in that line's grammar note. In particular, bare “illusion” is not an adequate replacement for `māyā`. For ordinary words, set `concept_key` to the empty string and `preserve_in_english=false`. If a new term seems irreducible but is not curated, do not add it: put the candidate and reason in uncertainty so publication stops for human review.

CURATED PRESERVED-TERM REGISTRY:
{json.dumps(term_registry, ensure_ascii=False)}

TARGET LYRICS (return these IDs only):
{json.dumps(batch, ensure_ascii=False)}

NEARBY CONTEXT (do not return these IDs unless also targets):
{json.dumps(context, ensure_ascii=False)}

Return strict JSON:
{{"glosses":[{{"id":"canonical-id","word_glosses":[{{"roman":"exact token","gloss":"short contextual meaning","concept_key":"","preserve_in_english":false}}],"semantic_frame":{{"agent":"","action_or_state":"","patient_or_complement":"","modifiers":"","negation_or_modality":"","literal_image_and_agency":"","idiom_or_phrase":"","cross_line_relation":""}},"grammar_note":"","uncertainty":""}}]}}"""
    schema = {"type": "object", "properties": {"glosses": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"}, "word_glosses": {"type": "array", "items": {"type": "object", "properties": {
                "roman": {"type": "string"}, "gloss": {"type": "string"},
                "concept_key": {"type": "string"}, "preserve_in_english": {"type": "boolean"}},
                "required": ["roman", "gloss", "concept_key", "preserve_in_english"], "additionalProperties": False}},
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
        result["packet"]["glosses"] = normalize_gloss_rows(lines, result["packet"].get("glosses", []))
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
                cached_rows = normalize_gloss_rows(batch, cached.get("response", {}).get("packet", {}).get("glosses", []))
                cached["response"]["packet"]["glosses"] = cached_rows
                if (cached.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
                        and not gloss_contract_errors(batch, cached_rows)):
                    return cached
            start = index * 40

            def request(target_lines: list[dict[str, Any]], absolute_start: int, label: str) -> dict[str, Any]:
                target_ids = [line["id"] for line in target_lines]
                context = (lines[max(0, absolute_start - 2):absolute_start]
                           + lines[absolute_start + len(target_lines):absolute_start + len(target_lines) + 2])
                response = gemini.call(options.model, gemini.key(), prompt_for(target_lines, context), audio=None,
                                       timeout=options.timeout, response_schema=schema,
                                       schema_name="bhakti_word_gloss_batch", reasoning_effort="high",
                                       max_completion_tokens=65536)
                response["packet"]["glosses"] = normalize_gloss_rows(
                    target_lines, response["packet"].get("glosses", [])
                )
                returned = [row.get("id") for row in response["packet"].get("glosses", [])]
                if returned != target_ids:
                    raise RuntimeError(f"gloss batch {label} returned IDs out of order or incomplete")
                mapping_errors = gloss_contract_errors(target_lines, response["packet"]["glosses"])
                if mapping_errors:
                    raise RuntimeError(f"gloss batch {label} violates surface-token mapping: {mapping_errors[:3]}")
                return response

            if len(batch) > 20:
                children = []
                for child_index, offset in enumerate(range(0, len(batch), 20)):
                    child = batch[offset:offset + 20]
                    child_ids = [line["id"] for line in child]
                    child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                    child_packet = read_packet(child_path)
                    if not (child_packet and child_packet.get("target_ids") == child_ids
                            and child_packet.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
                            and not options.force):
                        child_packet = {
                            "target_ids": child_ids,
                            "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                            "response": request(child, start + offset, f"{index}.{child_index}"),
                        }
                        write_json(child_path, child_packet)
                    children.append(child_packet)
                response = {
                    "packet": {"glosses": [row for child in children
                                            for row in child["response"]["packet"]["glosses"]]},
                    "resolved_model": options.model,
                }
                packet = {"target_ids": expected, "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                          "response": response, "child_batches": children}
            else:
                packet = {"target_ids": expected, "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                          "response": request(batch, start, str(index))}
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
    # Review outputs are verbose enough that 40-line packets can hit a model or
    # gateway output ceiling on long works. Twenty-line parent caches, issued as
    # ten-line requests below, keep evidence complete without a failed response.
    batches = [lines[index:index + 20] for index in range(0, len(lines), 20)]
    cache_dir = song_dir / ".transcription" / "pipeline" / "translation-review-batches"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def run(index: int) -> dict[str, Any]:
        batch = batches[index]
        expected = [line["id"] for line in batch]
        evidence = [{"source": line, "gloss": gloss_by_id[line["id"]],
                     "draft": translation_by_id[line["id"]]} for line in batch]
        fingerprint = hashlib.sha256(json.dumps(
            {"version": TRANSLATION_INPUT_VERSION, "model": gemini.batch_base_model(options.model), "evidence": evidence,
             "provided_translation": provided_translation}, ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest()
        path = cache_dir / f"batch-{index:03d}.json"
        cached = read_packet(path)
        if cached and cached.get("fingerprint") == fingerprint and not options.force:
            return cached
        def review_prompt(target_evidence: list[dict[str, Any]]) -> str:
            return f"""Act as an independent adversarial reviewer of devotional translations. You did not write the drafts. Do not rewrite them and do not optimize style.

For each line, compare the draft against the indexed glosses, semantic frame, grammar, source, neighboring relation, and material alternatives. Check separately: grammatical agency/experiencer; literal image and metaphor; every negation, modality, modifier and emphasis; unsupported additions; and whether two defensible readings differ materially in agency, metaphor, ambiguity, or poetic force.

Conventional English is not automatically better. Preserve personification, repetition, transparent spatial language, and concrete ritual images. A breath that abandons a speaker is materially different from a speaker releasing breath; a speaker who is broken from the inside is materially different from a speaker actively breaking; “takes hold” is materially different from “kindles”; palm is materially different from an abstract inner state. If the draft and an alternative make such a material choice and no locked human baseline resolves it, set human_review_recommended=true. Do not flag trivial synonyms or punctuation.

If a locked human translation is supplied and the draft copies it exactly, do not fail or rewrite it. If it conflicts with lexical evidence, keep passes=true but set human_review_recommended=true and explain the conflict for the human.

Set passes=false for lost meaning, changed agency/image, or unsupported additions. Return these IDs once in order. Strict JSON only.

EVIDENCE:
{json.dumps(target_evidence, ensure_ascii=False)}

LOCKED HUMAN TRANSLATION (or none):
{provided_translation}"""

        def request(target_evidence: list[dict[str, Any]], target_ids: list[str], label: str) -> dict[str, Any]:
            response = gemini.call(options.model, gemini.key(), review_prompt(target_evidence), audio=None,
                                   timeout=options.timeout, response_schema=translation_review_schema(),
                                   schema_name="bhakti_translation_review", reasoning_effort="high",
                                   max_completion_tokens=32768)
            reviews = response["packet"].get("reviews", [])
            observed = [row.get("id") for row in reviews]
            if len(observed) != len(target_ids) or set(observed) != set(target_ids):
                raise RuntimeError(f"translation review batch {label} returned IDs out of order or incomplete")
            if observed != target_ids:
                by_id = {row["id"]: row for row in reviews}
                response["packet"]["reviews"] = [by_id[item_id] for item_id in target_ids]
            return response

        if len(batch) > 10:
            children = []
            for child_index, offset in enumerate(range(0, len(batch), 10)):
                child_evidence = evidence[offset:offset + 10]
                child_ids = expected[offset:offset + 10]
                child_fingerprint = hashlib.sha256(json.dumps(
                    {"version": TRANSLATION_INPUT_VERSION, "model": gemini.batch_base_model(options.model),
                     "evidence": child_evidence, "provided_translation": provided_translation},
                    ensure_ascii=False, sort_keys=True,
                ).encode()).hexdigest()
                child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                child_packet = read_packet(child_path)
                if not (child_packet and child_packet.get("fingerprint") == child_fingerprint
                        and not options.force):
                    child_packet = {
                        "fingerprint": child_fingerprint,
                        "target_ids": child_ids,
                        "response": request(child_evidence, child_ids, f"{index}.{child_index}"),
                    }
                    write_json(child_path, child_packet)
                children.append(child_packet)
            response = {
                "packet": {"reviews": [row for child in children
                                        for row in child["response"]["packet"]["reviews"]]},
                "resolved_model": options.model,
            }
            result = {"fingerprint": fingerprint, "target_ids": expected,
                      "response": response, "child_batches": children}
        else:
            result = {"fingerprint": fingerprint, "target_ids": expected,
                      "response": request(evidence, expected, str(index))}
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
        term_registry = preserved_term_registry()
        return f"""Write faithful, complete English translations from the supplied word glosses, semantic frames, and grammar notes ONLY. The semantic frame is authoritative for agency, action/state, patient/complement, negation/modality, literal image, idiom, and cross-line syntax. Do not introduce a looser synonym, devotional interpretation, or omission that it does not support.

For each line, reason in this order before choosing the final English:
1. Compose the indexed token glosses into the closest grammatical English scaffold.
2. Check the scaffold against every semantic-frame field and neighboring line.
3. Preserve the source's agent, experiencer, and voice/state exactly. Never change “my breath abandons me” into “I breathe my last,” “I am broken from the inside” into “I broke from the inside,” a deity dwelling in a palm into an abstract spiritual state, or an interior image into a generic emotion merely because the alternative is conventional English.
4. Apply an established idiom only when `idiom_or_phrase` identifies it and the idiom does not erase a deliberate image. The devotional phrase `raham nazar` means “look upon [someone] with mercy”; do not render it as “cast a glance.” Conversely, do not invent a replacement metaphor such as “kindle” or “stir” when the source image is that a feeling “takes hold.” A possessed relational noun such as a garment hem should remain explicit rather than becoming an ambiguous “your hem.”
5. Make only the smallest grammatical adjustments needed for intelligible English. Prefer the source's transparent spatial vocabulary (“from the inside”) over a smoother intensifying substitute (“deep within”) unless depth is lexically present. Literal and poetic force outrank smoothness.
6. If a word has `preserve_in_english=true`, print the registry's canonical IAST term in `literal_english` and map that English segment to the word's index. Do not replace it with a forbidden flattening. Use the short word gloss only in the hover data, not as substitute prose in the lyric.

For each line, return plain literal English plus ordered display segments. Read adjacent lines as a continuous utterance before deciding syntax, punctuation, ellipsis, pronouns, or repeated words; a line may be a deliberate grammatical continuation. Each segment may reference the exact word indices which support it; punctuation or necessary English function-word segments can use an empty index list. Every source word index must appear in at least one segment. Map particles, postpositions, tense/aspect, negation, modality, and honorifics to the English phrase they help create rather than leaving their source index uncovered.

Write lucid devotional English, but do not confuse conventional English with better poetry. Literal strangeness, repetition, personification, unusual agency, and concrete bodily or ritual imagery may be the point. Preserve a supported image such as “my breath will abandon me” even if an English idiom such as “I will breathe my last” sounds smoother. Preserve suffered/resultant states as states: if the lyric says the speaker is broken, keep that brokenness rather than recasting it as the speaker actively broke. Never replace the source's agency, metaphor, ambiguity, or emotional logic merely to sound idiomatic. Correct wording only when it is demonstrably wrong, ungrammatical, or obstructs understanding. Avoid legalistic filler, accidental inversion, duplicate modifiers, and unsupported editorial verbs. Retain darshan or sacred vision, an alms bag, garment hem, cupped or open palm, lotus, dust, ocean, threshold, cage, and Mount Meru when the source supports them.

Use established English words. A rare but attested word is acceptable when it is precise and remains understandable in context. A transparent, source-supported compound may join two ordinary words, preferably with a hyphen when that aids reading. Never invent pseudo-Latin vocabulary or use a franchise-specific fictional coinage such as `adamantium`, `vibranium`, or `mithril`. `Adamantine` is an established English adjective and is not the fictional noun `adamantium`.

Resolve ordinary polysemy from the supplied grammar/song context. When two defensible renderings differ materially in agency, metaphor, ambiguity, or poetic force, include both in `material_alternatives` and set `human_review_recommended=true` instead of silently optimizing for smoothness. This is not required for trivial synonyms. The completed segments must reconstruct `literal_english` exactly, including ordinary spacing and punctuation. Then report a fidelity check: whether agency/image and all source meaning were preserved, every unsupported addition (normally none), and a concise note naming any nonliteral idiom or necessary English function word.

TARGET audited source lines (return these IDs only):
{json.dumps(batch, ensure_ascii=False)}

TARGET word gloss record:
{json.dumps(batch_glosses, ensure_ascii=False)}

CURATED PRESERVED-TERM REGISTRY:
{json.dumps(term_registry, ensure_ascii=False)}

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
        # Preserve the historical 40-line parent cache shape so already
        # completed work remains reusable, but issue fresh requests in bounded
        # 20-line children. Long translation JSON contains indexed segments and
        # fidelity evidence; a 40-line response can be truncated even with the
        # provider ceiling set to 65,536 tokens.
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

            def request(target_lines: list[dict[str, Any]], absolute_start: int, label: str) -> dict[str, Any]:
                target_ids = [line["id"] for line in target_lines]
                context = (lines[max(0, absolute_start - 2):absolute_start]
                           + lines[absolute_start + len(target_lines):absolute_start + len(target_lines) + 2])
                response = gemini.call(options.model, gemini.key(), prompt_for(target_lines, context), audio=None,
                                       timeout=options.timeout, response_schema=schema,
                                       schema_name="bhakti_translation_batch", reasoning_effort="high",
                                       max_completion_tokens=65536)
                returned = [row.get("id") for row in response["packet"].get("translations", [])]
                compared = [row.get("id") for row in response["packet"].get("comparison", [])]
                if returned != target_ids or compared != target_ids:
                    raise RuntimeError(f"translation batch {label} returned IDs out of order or incomplete")
                return response

            if len(batch) > 20:
                children = []
                for child_index, offset in enumerate(range(0, len(batch), 20)):
                    child = batch[offset:offset + 20]
                    child_ids = [line["id"] for line in child]
                    child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                    child_packet = read_packet(child_path)
                    if not (child_packet and child_packet.get("target_ids") == child_ids
                            and child_packet.get("input_contract_version") == TRANSLATION_INPUT_VERSION
                            and not options.force):
                        child_packet = {
                            "target_ids": child_ids,
                            "input_contract_version": TRANSLATION_INPUT_VERSION,
                            "response": request(child, start + offset, f"{index}.{child_index}"),
                        }
                        write_json(child_path, child_packet)
                    children.append(child_packet)
                response = {
                    "packet": {
                        "translations": [row for child in children
                                         for row in child["response"]["packet"]["translations"]],
                        "comparison": [row for child in children
                                       for row in child["response"]["packet"]["comparison"]],
                    },
                    "resolved_model": options.model,
                }
                packet = {"target_ids": expected, "input_contract_version": TRANSLATION_INPUT_VERSION,
                          "response": response, "child_batches": children}
            else:
                packet = {"target_ids": expected, "input_contract_version": TRANSLATION_INPUT_VERSION,
                          "response": request(batch, start, str(index))}
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
    registry = preserved_term_registry().get("terms", {})
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
        fictional = gloss_policy.fictional_coinages(translation.get("literal_english", ""))
        if fictional:
            errors.append(f"{line_id} translation uses fictional coinage {fictional}")
        for word in words:
            fictional = gloss_policy.fictional_coinages(word.get("gloss", ""))
            if fictional:
                errors.append(f"{line_id} word gloss uses fictional coinage {fictional}")
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
        linked_indices = {word_index for segment in translation.get("segments", [])
                          for word_index in segment.get("word_indices", []) if isinstance(word_index, int)}
        missing_indices = sorted(set(range(len(words))) - linked_indices)
        if missing_indices:
            errors.append(f"{line_id} English segments omit source word indices {missing_indices}")
        english = str(translation.get("literal_english", ""))
        for word_index, word in enumerate(words):
            if not word.get("preserve_in_english"):
                continue
            concept = registry.get(word.get("concept_key"), {})
            canonical = str(concept.get("iast", ""))
            if not canonical or canonical.casefold() not in english.casefold():
                errors.append(f"{line_id} must preserve {canonical or word.get('concept_key')} in English")
    return errors


def segment_english(parts: list[dict[str, Any]], fallback: str) -> str:
    if not parts:
        return fallback
    rendered: list[str] = []
    previous_text = ""
    for part in parts:
        text = str(part.get("text", ""))
        previous_trimmed = previous_text.rstrip()
        if (previous_trimmed.endswith(("-", "—", "…", "/", "(", '"', "'", "“", "‘"))
                and not previous_trimmed.endswith((" —", " –"))):
            text = text.lstrip()
        if (rendered and text and not text[0].isspace() and text[0] not in ",.;:!?…’')]}—–"
                and not previous_text.endswith(" ")
                and not previous_trimmed.endswith(("-", "—", "…", "/", "(", '"', "'", "“", "‘"))):
            text = " " + text
        indices = [str(index) for index in part.get("word_indices", []) if isinstance(index, int) and index >= 0]
        rendered.append("{" + ",".join(indices) + ":" + text + "}" if indices else text)
        previous_text = text
    return "".join(rendered)


def language_code(language: str) -> str:
    return {"Hindi": "hi", "Sanskrit": "sa", "Punjabi": "pa", "Kannada": "kn", "Marathi": "mr",
            "Braj": "bra"}.get(language, "")


def reviewed_display_title(candidate: str, lines: list[dict[str, Any]]) -> str:
    """Prefer the audited scholarly lyric when it is evidently the source title."""
    if not candidate or not lines:
        return candidate
    first = naming.canonical_iast(lines[0].get("roman", "")).strip()
    source_key = naming.compact(naming.common_romanization(candidate))
    lyric_key = naming.compact(naming.common_romanization(first))
    similar = difflib.SequenceMatcher(None, source_key, lyric_key).ratio()
    if first and similar >= 0.88 and abs(len(source_key.split()) - len(lyric_key.split())) <= 1:
        return first.title()
    return candidate


def page_html(meta: dict[str, Any]) -> str:
    title = meta["title"]
    escape = lambda text: (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                           .replace('"', "&quot;").replace("'", "&#39;"))
    people: dict[str, list[str]] = {}
    for field, label in (("writer", "Poet"), ("singer", "Singer"), ("vocalist", "Vocalist"),
                         ("composer", "Composer"), ("ensemble", "Recital")):
        person = str(meta.get(field) or "").strip()
        if person:
            people.setdefault(person, []).append(label)
    def display_roles(person: str, roles: list[str]) -> str:
        person_count = len([part for part in re.split(r"\s+(?:&|and)\s+", person, flags=re.I) if part])
        return " · ".join(
            role if role == "Recital" or person_count == 1 else f"{role}s" for role in roles
        )
    credits = "".join(
        f'<div class="song-credit-entry"><dt>{escape(display_roles(person, roles))}</dt><dd>{escape(person)}</dd></div>'
        for person, roles in people.items()
    )
    tags = "".join(
        f'<span class="song-tag subject-tag">{escape(tag)}</span>' for tag in meta.get("subjectTags", [])
    ) + "".join(
        f'<span class="song-tag language-tag">{escape(tag)}</span>' for tag in meta.get("languages", [])
    )
    credit_html = f'<dl class="song-credits">{credits}</dl>' if credits else ""
    tag_html = f'<div class="song-meta-tags" aria-label="Tags">{tags}</div>' if tags else ""
    meta_html = f'      <div class="song-meta">{credit_html}{tag_html}</div>\n'
    audio_sources = meta.get("audioSources") or [{"src": "audio.m4a", "type": "audio/mp4"}]
    source_html = "".join(f'<source src="{escape(source["src"])}" type="{escape(source["type"])}">' for source in audio_sources)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=2" />
  <meta name="theme-color" content="#6b0e16" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black" />
  <meta name="apple-mobile-web-app-title" content="Bhakti" />
  <link rel="icon" type="image/svg+xml" href="../../assets/favicon.svg" />
  <link rel="apple-touch-icon" href="../../assets/favicon.png" />
  <link rel="manifest" href="../../manifest.webmanifest" />
  <meta name="robots" content="noindex,nofollow,noarchive,nosnippet,noimageindex" />
  <meta name="referrer" content="no-referrer" />
  <title>{escape(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Cormorant+Garamond:ital,wght@0,300..700;1,300..700&family=EB+Garamond:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../../assets/style.css?v=contract-20260821-8" />
  <link rel="stylesheet" href="../../assets/song.css?v=contract-20260821-13" />
</head>
<body>
  <main class="song-page">
    <header class="song-hero">
      <div class="song-top-controls" aria-label="Song controls">
        <button class="song-sync" id="songSync" type="button" aria-label="Keep lyrics synced to playback" aria-pressed="true" title="Lyrics follow playback"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m10.6 13.4 2.8-2.8"/><path d="M7.7 16.3l-1.4 1.4a3.25 3.25 0 0 1-4.6-4.6l4-4a3.25 3.25 0 0 1 4.6 0"/><path d="M16.3 7.7l1.4-1.4a3.25 3.25 0 0 1 4.6 4.6l-4 4a3.25 3.25 0 0 1-4.6 0"/></svg></button>
        <button class="song-share" id="songShare" type="button" aria-label="Share this song" title="Share"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 15.2V3.8m0 0L8.3 7.5M12 3.8l3.7 3.7M5 12.5v5.7c0 .99.81 1.8 1.8 1.8h10.4c.99 0 1.8-.81 1.8-1.8v-5.7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      </div>
      <h1 class="song-title">{escape(title)}</h1>
{meta_html}      <p class="song-hint">Tap or hover over any word to see its meaning.</p>
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
  <script src="data.js?v=contract-20260822-1"></script>
  <script src="../../assets/song.js?v=contract-20260822-1"></script>
  <script src="../../assets/pwa.js?v=contract-20260821-8"></script>
</body>
</html>
'''


def load_song_meta(song_dir: Path) -> dict[str, Any] | None:
    path = song_dir / "data.js"
    if not path.is_file():
        return None
    script = "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.SONG_META||{}));"
    output = subprocess.run(["node", "-e", script, str(path)], check=True, text=True, capture_output=True).stdout
    value = json.loads(output)
    return value if isinstance(value, dict) else None


def catalogue_sort_key(entry: dict[str, Any]) -> tuple[str, str, str, str, str]:
    singer = naming.compact(str(entry.get("singer") or ""))
    writer = naming.compact(str(entry.get("writer") or ""))
    subject = naming.compact(" ".join(str(value) for value in (entry.get("subjectTags") or [])))
    language = naming.compact(" ".join(str(value) for value in (entry.get("languageTags") or [])))
    title = naming.compact(str(entry.get("title") or entry.get("slug") or ""))
    return (singer or writer or title, subject, language, title, naming.compact(str(entry.get("slug") or "")))


def catalogue_entry(song_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "slug": song_dir.name,
        "title": str(meta.get("title") or song_dir.name.replace("-", " ").title()),
        "credit": str(meta.get("credit") or ""),
        "languageTags": list(meta.get("languages") or []),
        "subjectTags": list(meta.get("subjectTags") or []),
        "searchAliases": list(meta.get("searchAliases") or []),
        "writer": str(meta.get("writer") or ""),
        "singer": str(meta.get("singer") or ""),
        "composer": str(meta.get("composer") or ""),
    }
    subtitle = str(meta.get("subtitle") or "").strip()
    if subtitle:
        entry["subtitle"] = subtitle
    return entry


def write_catalogue() -> None:
    catalogue: list[dict[str, Any]] = []
    for song_dir in sorted((ROOT / "songs").glob("*")):
        if not song_dir.is_dir():
            continue
        meta = load_song_meta(song_dir)
        if not meta:
            continue
        catalogue.append(catalogue_entry(song_dir, meta))
    catalogue.sort(key=catalogue_sort_key)
    (ROOT / "data" / "songs.js").write_text(
        "window.BHAKTI_SONGS = " + json.dumps(catalogue, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def load_catalogue() -> list[dict[str, Any]]:
    write_catalogue()
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


def generate(song_dir: Path, job: dict[str, Any], source: dict[str, Any], audited: dict[str, Any], timing: dict[str, Any], glosses: dict[str, Any], translations: dict[str, Any], *, write_catalogue_after: bool = True) -> None:
    errors = publication_errors(audited, timing, glosses, translations)
    if errors:
        raise RuntimeError("publication blocked: " + "; ".join(errors))
    lines = audited["packet"].get("verified_lines", [])
    gloss_rows = glosses["packet"].get("glosses", [])
    translation_rows = translations["packet"].get("translations", [])
    gloss_by_id = {row["id"]: row for row in gloss_rows}
    translation_by_id = {row["id"]: row for row in translation_rows}
    meta_from_model = audited["packet"].get("metadata", {})
    raw_title = job.get("displayTitle") or job.get("title") or source.get("title") or job["slug"].replace("-", " ").title()
    title = str(raw_title) if job.get("displayTitle") else reviewed_display_title(str(raw_title), lines)
    # Do not manufacture a public role from a model candidate. Callers may
    # supply researched roles; otherwise the compact credit line is absent.
    writer = naming.canonical_person(job.get("writer", ""))
    singer = naming.canonical_person(job.get("singer") or source.get("artist") or "")
    vocalist = naming.canonical_person(job.get("vocalist", ""))
    composer = naming.canonical_person(job.get("composer") or source.get("composer") or "")
    ensemble = str(job.get("ensemble") or "").strip()
    distinct_people = list(dict.fromkeys(person for person in (writer, singer, composer) if person))
    credit = str(job.get("credit", "")).strip() or " · ".join(distinct_people)
    page_credit = str(job.get("pageCredit", "")).strip() or singer or credit
    subjects = tag_taxonomy.merge_subject_tags(job.get("subjectTags", []), lines)
    subtitle = str(job.get("subtitle", "")).strip() or (subjects[0] if subjects else "")
    aliases = naming.search_aliases(
        [job["slug"].replace("-", " "), title, subtitle, credit, page_credit,
         writer, singer, vocalist, composer, ensemble, *subjects, *(job.get("languages") or meta_from_model.get("languages", []))],
        [*naming.person_search_aliases((job.get("writer"), job.get("singer"), job.get("vocalist"), job.get("composer"), writer, singer, vocalist, composer)),
         *(job.get("searchAliases") or [])],
    )
    languages = list(dict.fromkeys(normalized_language(str(language))
                                   for language in (job.get("languages") or meta_from_model.get("languages", []))
                                   if str(language).strip()))
    meta = {"title": title, "subtitle": subtitle, "credit": credit, "pageCredit": page_credit,
            "writer": writer, "singer": singer, "vocalist": vocalist, "composer": composer, "ensemble": ensemble,
            "languages": languages,
            "subjectTags": subjects, "searchAliases": aliases,
            "audioSources": published_audio_sources(song_dir),
            "timingStatus": "start-only-reviewed",
            "translationStatus": "gloss-derived literal",
            "sourceStatus": "reviewed"}
    line_data: dict[str, Any] = {}
    for line in lines:
        line_id = line["id"]
        row = translation_by_id[line_id]
        words = [gloss_policy.clean_word({**word, "roman": naming.canonical_iast(word.get("roman", ""))})
                 for word in gloss_by_id[line_id].get("word_glosses", [])]
        source = line.get("source_text", "")
        line_data[line_id] = {"source": source, "sourceLanguage": language_code((meta["languages"] or [""])[0]),
                              "sourceWords": source_word_map.build_source_words(source, words),
                              "roman": naming.canonical_iast(line.get("roman", "")), "english": segment_english(row.get("segments", []), row.get("literal_english", "")),
                              "words": words,
                              "grammarNote": naming.canonical_iast(gloss_by_id[line_id].get("grammar_note", ""))}
    sequence = [{"ref": event["ref"],
                 "section": event.get("section") or next((line.get("kind", "verse")
                                                           for line in lines if line["id"] == event["ref"]), "verse"),
                 "repeats": int(event.get("repeats", 1) or 1)}
                for event in timing["sequence"]]
    times = [{"start": round(event["start"], 3), "end": round(event["end"], 3)} for event in timing["sequence"]]
    sequence, times, _ = compress_adjacent_reader_entries(sequence, times)
    data = ("window.SONG_META = " + json.dumps(meta, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_LINES = " + json.dumps(line_data, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_SEQUENCE = " + json.dumps(sequence, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_TIMINGS = " + json.dumps(times, ensure_ascii=False, indent=2) + ";\n")
    (song_dir / "data.js").write_text(data, encoding="utf-8")
    (song_dir / "index.html").write_text(page_html(meta), encoding="utf-8")
    if write_catalogue_after:
        write_catalogue()


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


def preflight_blocked_reason(options: argparse.Namespace) -> str | None:
    if options.generate_only or gemini.provider_name() != "openrouter":
        return None
    try:
        status = gemini.openrouter_account_status(gemini.key(), timeout=min(20.0, options.timeout))
    except (OSError, RuntimeError, ValueError):
        return None
    if status.get("credits_exhausted"):
        return (
            "OpenRouter credits are exhausted for the shared Dev key "
            f"({status.get('total_usage')} used of {status.get('total_credits')}). "
            "Add credits at https://openrouter.ai/settings/credits before running Bhakti intake."
        )
    return None


def is_sanskrit_first_pass(raw: dict[str, Any]) -> bool:
    metadata = raw.get("packet", {}).get("metadata", {})
    languages = metadata.get("languages", []) if isinstance(metadata, dict) else []
    return any(normalized_language(str(language)) == "Sanskrit" for language in languages)


def language_hold_packet(song_dir: Path, source: dict[str, Any], raw: dict[str, Any], started: float) -> dict[str, Any]:
    """Persist the first-pass evidence but deliberately stop an uncertain song.

    This is used only for an explicitly opt-in intake queue. It lets a first
    transcription determine whether a conservatively held recording is Sanskrit
    without pretending a partial record is publishable or deleting the audio.
    """
    packet = {
        "source": source,
        "created_at": time.time(),
        "transcript": raw,
        "publication_status": "held-language",
        "language_hold_reason": "First transcription identified Sanskrit; audit, timing, glossing, translation, and reader generation were intentionally skipped.",
        "elapsed_seconds": round(time.time() - started, 2),
        "reported_openrouter_cost": reported_cost(raw),
    }
    write_json(song_dir / ".transcription" / "pipeline" / "song-packet.json", packet)
    return packet


def hydrate_pipeline_artifacts(packet_dir: Path) -> None:
    summary = read_packet(packet_dir / "song-packet.json") or {}
    for filename, key in (
        ("01-transcript.json", "transcript"),
        ("02-transcript-audit.json", "audit"),
        ("03-timing.json", "timing"),
        ("04-glosses.json", "glosses"),
        ("05-translation.json", "translation"),
    ):
        path = packet_dir / filename
        value = summary.get(key)
        if path.is_file() or not isinstance(value, dict):
            continue
        write_json(path, value)


def run_one(job: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    song_dir, source = intake(job, force=options.force)
    if "youtube.com" in str(source.get("source_url", "")) or "youtu.be" in str(source.get("source_url", "")):
        trim = detect_youtube_trim(song_dir, source, options)
        apply_lossless_trim(song_dir, trim)
    audio = preferred_listener_audio(song_dir)
    started = time.time()
    raw = transcript(song_dir, source, audio, options)
    if job.get("holdIfSanskrit") and is_sanskrit_first_pass(raw):
        packet = language_hold_packet(song_dir, source, raw, started)
        return {"slug": job["slug"], "status": packet["publication_status"],
                "elapsed_seconds": packet["elapsed_seconds"],
                "reported_openrouter_cost": packet["reported_openrouter_cost"]}
    if options.source_witness_audit:
        # Preserve the first audio transcription. A witness is deliberately a
        # second-pass aid, so only dependent artifacts are invalidated.
        packet_dir = song_dir / ".transcription" / "pipeline"
        for filename in ("02-transcript-audit.json", "03-timing.json", "04-glosses.json", "05-translation.json", "song-packet.json"):
            (packet_dir / filename).unlink(missing_ok=True)
    elif options.refresh_timing:
        packet_dir = song_dir / ".transcription" / "pipeline"
        (packet_dir / "03-timing.json").unlink(missing_ok=True)
        (packet_dir / "song-packet.json").unlink(missing_ok=True)
        # A timing refresh must remeasure every bounded long-recording window;
        # retaining a prior disputed window would merely reproduce the onset
        # it was asked to repair.
        shutil.rmtree(packet_dir / "long-timing-segments", ignore_errors=True)
    audited = audit_transcript(song_dir, raw, audio, options)
    if audited.pop("merge_contract_rebuilt", False):
        # A new deterministic reconciliation can alter canonical lines and
        # occurrence order. Reuse audio evidence but never keep glosses or
        # translations derived from the old source surface. Their per-batch
        # caches are keyed by the prior canonical IDs, so retaining them would
        # silently splice stale word maps into the newly merged text.
        packet_dir = song_dir / ".transcription" / "pipeline"
        for filename in ("04-glosses.json", "05-translation.json"):
            (packet_dir / filename).unlink(missing_ok=True)
        for directory in ("long-timing-segments", "gloss-batches", "translation-batches", "translation-review-batches"):
            shutil.rmtree(packet_dir / directory, ignore_errors=True)
        write_json(packet_dir / "02-transcript-audit.json", audited)
    if apply_verified_text_corrections(song_dir, audited):
        packet_dir = song_dir / ".transcription" / "pipeline"
        write_json(packet_dir / "02-transcript-audit.json", audited)
        # Gloss and translation results depend on the old source surface.
        for filename in ("04-glosses.json", "05-translation.json"):
            (packet_dir / filename).unlink(missing_ok=True)
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
    if options.economy:
        options.model = economy_model(options.model)
    jobs = normalise_jobs(options)
    results: list[dict[str, Any]] = []
    blocked_reason = preflight_blocked_reason(options)
    if blocked_reason:
        results = [{"slug": job["slug"], "status": "blocked", "error": blocked_reason} for job in jobs]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1
    if options.generate_only:
        options.publish = True
        results = [{"slug": job["slug"], "status": "review-required", "reported_openrouter_cost": 0.0}
                   for job in jobs]
    else:
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
            hydrate_pipeline_artifacts(packet_dir)
            source = read_packet(song_dir / ".transcription" / "source.json") or {}
            audited = read_packet(packet_dir / "02-transcript-audit.json")
            timing = read_packet(packet_dir / "03-timing.json")
            glosses = read_packet(packet_dir / "04-glosses.json")
            translations = read_packet(packet_dir / "05-translation.json")
            try:
                if not all((audited, timing, glosses, translations)):
                    raise RuntimeError(f"missing pipeline artifact for {job['slug']}")
                generate(song_dir, job, source, audited, timing, glosses, translations, write_catalogue_after=False)
                summary = read_packet(packet_dir / "song-packet.json") or {}
                summary["publication_status"] = "generated"
                write_json(packet_dir / "song-packet.json", summary)
                result["status"] = "generated"
            except Exception as exc:
                result["status"] = "blocked"
                result["error"] = str(exc)
        write_catalogue()
    print(json.dumps(sorted(results, key=lambda item: item["slug"]), ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "blocked" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
