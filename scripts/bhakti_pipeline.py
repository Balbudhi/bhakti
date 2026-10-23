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
import copy
import difflib
import hashlib
import json
import math
import os
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
import bhakti_lexical_support
import bhakti_translation_policy
import bhakti_semantic_repair
import editorial_baselines
from display_word_map import clean_display_word_map
import naming
import resolve_youtube_music_audio as ytmusic
import tag_taxonomy
import source_word_map
import source_witness
import scripture_metadata


ROOT = Path(__file__).resolve().parents[1]
SITE_ORIGIN = "https://bhakti.eeshan.xyz"
MODEL = gemini.MODEL
LONG_MERGE_VERSION = 8
LONG_TRANSCRIPT_CONTRACT_VERSION = 4
GLOSS_CONTRACT_VERSION = 6
TRANSLATION_INPUT_VERSION = 9
SEMANTIC_FRAME_FIELDS = (
    "agent", "action_or_state", "patient_or_complement", "modifiers",
    "negation_or_modality", "literal_image_and_agency", "idiom_or_phrase",
    "cross_line_relation",
)


def preserved_term_registry() -> dict[str, Any]:
    return json.loads((ROOT / "data" / "preserved_terms.json").read_text(encoding="utf-8"))


def translation_policy_payload() -> dict[str, Any]:
    """Snapshot all lexical policy that can affect cached text judgments."""
    return {"preserved_terms": preserved_term_registry(),
            "lexical_policy": bhakti_translation_policy.policy_payload(),
            "reading_context_contract": 1, "context_findings_contract": 2}


def text_stage_fingerprint(stage: str, model: str, inputs: dict[str, Any],
                           policy: dict[str, Any]) -> str:
    """Bind a cached judgment to its exact evidence, model and policy."""
    payload = {"stage": stage, "gloss_version": GLOSS_CONTRACT_VERSION,
               "translation_version": TRANSLATION_INPUT_VERSION,
               "model": gemini.batch_base_model(model), "provider": gemini.provider_name(),
               "policy": policy, "inputs": inputs}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def translation_stage_inputs(lines, gloss_rows, provided_translation, languages, options, *, performance_order=()):
    """One current evidence identity for translation creation and draft adoption."""
    return {"lines": lines, "glosses": gloss_rows, "provided_translation": provided_translation,
            "languages": languages, "reading_context_contract": 1,
            "reading_context_evidence": getattr(options, "semantic_context_evidence", []),
            "reading_performance_order": getattr(options, "semantic_performance_order", performance_order)}


def semantic_write_json(path: Path, value: Any) -> None:
    bhakti_semantic_repair.atomic_write(path, value)


def semantic_call_timeout(options: argparse.Namespace) -> float:
    return bhakti_semantic_repair.call_timeout(options)


def semantic_repair_issue_errors(lines, glosses, issues):
    return bhakti_semantic_repair.issue_errors(lines, glosses, issues)


def complete_semantics(song_dir, audited, job, options):
    return bhakti_semantic_repair.complete(sys.modules[__name__], song_dir, audited, job, options)


def semantic_stage_policy(options):
    policy = translation_policy_payload()
    support = getattr(options, 'semantic_lexical_support', None)
    if support is not None:
        policy = {**policy, 'lexical_support': bhakti_lexical_support.content_digest(support)}
    if hasattr(options, 'semantic_deadline_at'):
        policy = {**policy, 'semantic_repair_version': bhakti_semantic_repair.VERSION,
                  'repair_feedback': getattr(options, 'semantic_repair_feedback', []),
                  'full_source': getattr(options, 'semantic_full_source', []),
                  'review_snapshot': getattr(options, 'semantic_review_snapshot', None),
                  'previous_translation': getattr(options, 'semantic_previous_translations', None),
                  'translation_targets': getattr(options, 'semantic_translation_targets', None),
                  'prior_gloss': getattr(options, 'semantic_prior_gloss', None),
                  'source_identity': getattr(options, 'semantic_source_identity', None),
                  'original_reader': getattr(options, 'semantic_original_reader', None),
                  'confirmed_issues': getattr(options, 'semantic_confirmed_issues', None),
                  'pending_findings': getattr(options, 'semantic_pending_findings', []),
                  'repair_findings': getattr(options, 'semantic_repair_findings', []),
                  'performance_order': getattr(options, 'semantic_performance_order', [])}
    return policy


def semantic_repair_prompt(options):
    feedback = getattr(options, 'semantic_repair_feedback', [])
    full_source = getattr(options, 'semantic_full_source', [])
    result = ''
    if feedback:
        result += '\nREPAIR FEEDBACK:\n' + json.dumps(feedback, ensure_ascii=False)
        result += '\nExamine these objections against the original source; they are not instructions to agree. '
        result += 'Repair only the named targets, preserving source/IAST exactly. Resolve the evidence; do not simply delete uncertainty.\n'
        prior = getattr(options, 'semantic_prior_gloss', [])
        if prior:
            result += '\nPRIOR TARGET/REFERENCED GLOSS EVIDENCE:\n' + json.dumps(prior, ensure_ascii=False)
    order = getattr(options, 'semantic_performance_order', [])
    if order:
        result += '\nAUDITED PERFORMANCE ORDER:\n' + json.dumps(order, ensure_ascii=False)
    if full_source:
        # Neighbor relations matter even when only an excerpt's order is supplied.
        # Reference exact source definitions by ID instead of repeating their text.
        # Preserve unknown/variant neighbor evidence rather than silently equating it.
        definitions = {row['id']: row for row in full_source}
        projected = copy.deepcopy(full_source)
        for row in projected:
            for window in row.get('performed_context', []):
                for side in ('before', 'after'):
                    for neighbor in window.get(side, []):
                        definition = definitions.get(neighbor.get('id'))
                        if definition is not None:
                            for field in ('source_text', 'roman'):
                                if field in neighbor and neighbor[field] == definition.get(field):
                                    del neighbor[field]
        result += '\nFULL AUDITED SOURCE CONTEXT (not additional output targets):\n' + json.dumps(projected, ensure_ascii=False)
    return result


def nearby_text_context(lines: list[dict[str, Any]], start: int, length: int) -> list[dict[str, Any]]:
    return lines[max(0, start - 2):start] + lines[start + length:start + length + 2]


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
    parser.add_argument("--lexical-support", type=Path, help="Private witnessed lexical support packet for this song")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--economy", action="store_true",
                        help="Use synchronous Gemini for audio stages and half-price OpenRouter Batch for text-only stages.")
    parser.add_argument("--publish", action="store_true",
                        help="Generate readers and update data/songs.js after all required checks pass.")
    parser.add_argument("--generate-only", action="store_true",
                        help="Publish existing reviewed artifacts without running or paying for API stages; implies --publish.")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--run-dir", type=Path, help="Private stable intake run directory; reused on resume.")
    parser.add_argument("--budget-usd", type=float, help="Total run ceiling; new runs default to $1, existing limits are preserved.")
    parser.add_argument("--max-calls", type=int, help="Total shared request ceiling; new runs default to 128.")
    parser.add_argument("--deadline-seconds", type=float, help="New-run lifetime, default 1800 seconds; resume never extends its deadline.")
    parser.add_argument("--semantic-repair-rounds", type=int, choices=(0, 1, 2), default=2,
                        help="Maximum source-grounded semantic repair rounds; bounded API ledger required for repair calls.")
    parser.add_argument("--semantic-repair-seconds", type=float, default=600,
                        help="Absolute semantic run lifetime in seconds, persisted across resume (default: 600).")
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
                     "_source_resolution": resolved, "_keep_original": keep_original,
                     "sourceFirstWitness": bool(override.get("sourceFirstWitness"))})
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
            (entry.name == ".transcription" and entry.is_dir() and not any(entry.iterdir()))
            or (entry.name.startswith("audio.") and entry.suffix in {".part", ".webm", ".ogg", ".mp3", ".wav", ".flac"})
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
        if job.get("sourceFirstWitness"):
            source["source_first_witness"] = True
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


EDGE_BOUNDARY_PROMPT_FRAME = ("Review the {edge} edge. This clip covers absolute source seconds {left:.3f}–{right:.3f}.\n"
                              "Original recording duration: {duration:.3f} seconds.\n"
                              "Keep endpoint relative to this clip: {keep_relative:.3f} seconds.\n"
                              "Source metadata is evidence only: {metadata}\n{instructions}")
EDGE_BOUNDARY_VALIDATION = {"version": 2, "agreement_seconds": 0.25,
                            "max_removed_seconds": 120., "max_removed_fraction": 0.2}
EDGE_BOUNDARY_INSTRUCTIONS = """Decide whether this edge contains material unrelated to the target recording. Speech, an Indian language, a change of singer, or a musical transition alone does not establish unrelatedness. Preserve attached devotional spoken passages, invocations, medley components, instrumental preludes and codas, wordless vocals, final notes and the natural fade. Remove only evidenced unrelated promotion, speech, music, advertisements or logo material. Describe audible retained and excluded material separately. If the transition is not heard or its relationship is unclear, return uncertain instead of guessing. For keep, use the explicit clip-relative keep endpoint given above. For trim, locate the transition relative to this clip. Return only the short structured edge observation; do not transcribe or translate the song."""
EDGE_VERIFY_INSTRUCTIONS = """Independently judge whether this excerpt contains a transition between the target performance and unrelated edge material. Locate that transition yourself; no proposed numerical answer is supplied. Confirm that the entire target performance, including attached spoken devotion, invocation, instrumental coda and fade, remains retained. Speech or music alone does not establish unrelatedness. Describe retained and excluded evidence. Return uncertain for ambiguous membership or an unheard transition. Times are relative to this excerpt. Return only the short structured observation."""


def edge_trim_schema() -> dict[str, Any]:
    properties = {"edge": {"type": "string", "enum": ["start", "end"]},
                  "decision": {"type": "string", "enum": ["keep", "trim", "uncertain"]},
                  "boundary": {"type": "number"}, "outside_type": {"type": "string"},
                  "relationship": {"type": "string", "enum": ["attached_to_work", "unrelated", "uncertain"]},
                  "confidence": {"type": "string", "enum": ["high", "low"]},
                  "retained_evidence": {"type": "string"}, "excluded_evidence": {"type": "string"},
                  "reason": {"type": "string"}}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def detect_youtube_trim(song_dir: Path, source: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    """Review local or remote-source edges using the preserved original time axis."""
    import bhakti_model_routes as routes

    base_model = gemini.batch_base_model(options.model)
    review_dir = song_dir / ".transcription"
    target = review_dir / "trim-review.json"
    manifest = read_packet(review_dir / "trim-originals.json") or {}
    marker = read_packet(review_dir / "trim-applied.json") or {}
    if manifest.get("version") == 2 and manifest.get("sources"):
        first = manifest["sources"][0]
        audio = review_dir / "original-audio" / first["src"]
        if not audio.is_file() or hashlib.sha256(audio.read_bytes()).hexdigest() != first["sha256"]:
            raise RuntimeError("preserved original audio identity changed before edge review")
    elif marker.get("applied"):
        raise RuntimeError("legacy trimmed audio has no preserved original for boundary review")
    else:
        audio = preferred_listener_audio(song_dir)
    duration = gemini.duration_seconds(audio)
    metadata = {key: source.get(key) for key in ("title", "artist", "channel", "source_url", "source_file") if source.get(key)}
    identity = {"version": 2, "source_audio": audio.name, "source_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                "duration": duration, "metadata": metadata, "model": base_model,
                "pro_model": getattr(options, "pro_model", routes.PRO_MODEL), "schema": edge_trim_schema(),
                "question": EDGE_BOUNDARY_INSTRUCTIONS, "verification_question": EDGE_VERIFY_INSTRUCTIONS,
                "prompt_frame": EDGE_BOUNDARY_PROMPT_FRAME, "validation": EDGE_BOUNDARY_VALIDATION,
                "flash_edge_seconds": 75., "pro_edge_seconds": 150., "verification_radius": 15.,
                "codec": "aac", "bitrate": "192k", "reasoning": "medium", "output_tokens": 2048}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cached = read_packet(target)
    if cached and cached.get("input_fingerprint") == fingerprint:
        normalized = normalize_trim_artifact(cached)
        if not normalized["validation_errors"]:
            return normalized
    base = {"boundary_contract_version": 2, "duration": duration, "source_audio": audio.name,
            "source_sha256": identity["source_sha256"], "input_fingerprint": fingerprint}
    deadline = getattr(options, "boundary_deadline_at", None) or getattr(options, "unit_deadline_at", None)
    if deadline is None:
        deadline = time.time() + float(options.timeout) * 4

    def keep_edge(edge: str) -> dict[str, Any]:
        return {"edge": edge, "clip_start": 0., "clip_end": duration, "response": {"packet": {
            "edge": edge, "decision": "keep", "boundary": 0. if edge == "start" else duration,
            "outside_type": "none", "relationship": "attached_to_work", "confidence": "high",
            "retained_evidence": "Other edge is outside this unit's validation scope.", "excluded_evidence": "", "reason": "Context only."}}}

    def run(edge: str) -> dict[str, Any]:
        def execute(ctx: Any) -> dict[str, Any]:
            length = min(duration, 75. if ctx.model == base_model else 150.)
            start = 0. if edge == "start" else duration - length

            def hear(left: float, right: float, verify: bool) -> dict[str, Any]:
                name = f"{edge}-{'verify' if verify else 'classify'}"
                clip = ctx.attempt_dir / f"{name}.m4a"
                subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{left:.3f}",
                                "-i", str(audio), "-t", f"{right-left:.3f}", "-vn", "-c:a", "aac", "-b:a", "192k", str(clip)], check=True)
                instructions = EDGE_VERIFY_INSTRUCTIONS if verify else EDGE_BOUNDARY_INSTRUCTIONS
                prompt = EDGE_BOUNDARY_PROMPT_FRAME.format(edge=edge, left=left, right=right, duration=duration,
                    metadata=json.dumps(metadata, ensure_ascii=False), instructions=instructions,
                    keep_relative=0. if edge == "start" else duration-left)
                response = gemini.call(ctx.model, gemini.key(), prompt, audio=clip, timeout=ctx.call_timeout_seconds,
                    response_schema=edge_trim_schema(), schema_name=f"bhakti_{name.replace('-', '_')}",
                    reasoning_effort="medium", max_completion_tokens=2048,
                    unit_context=ctx.transport_context, deadline_at=ctx.deadline_at)
                return {"edge": edge, "clip_start": left, "clip_end": right, "response": response}

            observed = hear(start, start + length, False)
            packet = observed.get("response", {}).get("packet", {})
            boundary = packet.get("boundary")
            if (packet.get("decision") == "trim" and packet.get("relationship") == "unrelated"
                    and packet.get("confidence") == "high" and isinstance(boundary, (int, float))
                    and not isinstance(boundary, bool) and math.isfinite(boundary) and 0 <= boundary <= length):
                absolute = start + boundary
                observed["verification"] = hear(max(0., absolute - 15.), min(duration, absolute + 15.), True)
            return observed

        def validate(observed: dict[str, Any]) -> list[dict[str, str]]:
            packet = {**base, "start": keep_edge("start"), "end": keep_edge("end"), edge: observed}
            errors = normalize_trim_artifact(packet)["validation_errors"]
            return [{"kind": "boundary_disagreement", "detail": detail} for detail in errors]

        return routes.run_unit(review_dir / "boundary-routes", f"edge:{edge}", fingerprint, execute, validate,
            deadline_at=deadline, base_model=base_model, pro_model=identity["pro_model"],
            policy=routes.EscalationPolicy(call_timeout_seconds=min(600., float(options.timeout))))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(run, ("start", "end")))
    artifact = normalize_trim_artifact({**base, **{row["edge"]: row for row in rows}})
    write_json(target, artifact)
    return artifact

def normalize_trim_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Validate edge evidence in the immutable original recording's time axis.

    V2 accepts a removal only with independent relationship/transition evidence.
    The 250 ms bound is agreement tolerance, not a claim of acoustic accuracy;
    accepted differences retain more audio. Legacy evidence is never upgraded.
    """
    legacy_categories = {"platform_spoken", "channel_promotion", "spoken_intro", "spoken_narration", "spoken_framing", "spoken_promotion",
                         "promotion", "advertisement", "logo_sting", "countdown", "unrelated_narration",
                         "post_song_film_dialogue"}
    errors: list[str] = []
    version = artifact.get("boundary_contract_version", 1)
    if version not in (1, 2):
        errors.append("unsupported boundary evidence contract")
    if version == 2:
        digest = artifact.get("source_sha256")
        name = artifact.get("source_audio")
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            errors.append("original audio SHA256 is missing or invalid")
        if not isinstance(name, str) or Path(name).name != name or not name.startswith("audio."):
            errors.append("original audio name is missing or invalid")

    def number(value: Any, label: str) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append(f"{label} must be finite numeric seconds")
            return None
        return float(value)

    duration = number(artifact.get("duration"), "duration")
    bounds = {"start": 0.0, "end": duration or 0.0}
    if duration is None or duration <= 0:
        errors.append("original duration must be positive")
    else:
        edge_length = min(75.0, duration)

        def observation(row: Any, edge: str, label: str) -> tuple[dict[str, Any], float] | None:
            response = row.get("response") if isinstance(row, dict) else None
            packet = response.get("packet") if isinstance(response, dict) else None
            if not isinstance(packet, dict):
                errors.append(f"{label} observation is missing")
                return None
            if packet.get("edge", edge if version == 1 else None) != edge or row.get("edge", edge) != edge:
                errors.append(f"{label} observation has a mismatched edge")
            default_start = 0.0 if edge == "start" else duration - edge_length
            clip_start = number(row.get("clip_start", default_start if version == 1 else None), f"{label} clip start")
            default_end = clip_start + edge_length if clip_start is not None else None
            clip_end = number(row.get("clip_end", default_end if version == 1 else None), f"{label} clip end")
            boundary = number(packet.get("boundary"), f"{label} boundary")
            if clip_start is None or clip_end is None or boundary is None:
                return None
            if not 0 <= clip_start < clip_end <= duration:
                errors.append(f"{label} observed clip is outside the original recording")
            if not 0 <= boundary <= clip_end - clip_start:
                errors.append(f"{label} boundary is outside the observed clip")
            if str(packet.get("confidence", "")).casefold() != "high":
                errors.append(f"{label} observation is uncertain")
            decision = packet.get("decision")
            if decision not in {"keep", "trim"}:
                errors.append(f"{label} decision is unresolved")
            if version == 2:
                expected_relation = "unrelated" if decision == "trim" else "attached_to_work"
                if packet.get("relationship") != expected_relation:
                    errors.append(f"{label} relationship is unresolved or contradicts the decision")
                if not isinstance(packet.get("retained_evidence"), str) or not packet["retained_evidence"].strip():
                    errors.append(f"{label} lacks retained-performance evidence")
                if decision == "trim" and (not isinstance(packet.get("excluded_evidence"), str) or not packet["excluded_evidence"].strip()):
                    errors.append(f"{label} lacks unrelated-material evidence")
            return packet, clip_start + boundary

        for edge in ("start", "end"):
            row = artifact.get(edge)
            observed = observation(row, edge, edge)
            if observed is None:
                continue
            packet, absolute = observed
            if packet.get("decision") == "trim":
                bounds[edge] = absolute
                if version == 1:
                    if str(packet.get("outside_type", "")).casefold() not in legacy_categories:
                        errors.append(f"{edge} removal category requires relationship review")
                else:
                    checked = observation(row.get("verification"), edge, f"{edge} verification")
                    if checked is not None:
                        check_packet, check_absolute = checked
                        if check_packet.get("decision") != "trim":
                            errors.append(f"{edge} independent review disagrees about removal")
                        if abs(absolute - check_absolute) > EDGE_BOUNDARY_VALIDATION["agreement_seconds"]:
                            errors.append(f"{edge} independent boundaries disagree")
                        bounds[edge] = min(absolute, check_absolute) if edge == "start" else max(absolute, check_absolute)
            elif packet.get("decision") == "keep":
                expected = 0.0 if edge == "start" else duration
                if abs(absolute - expected) > 0.001:
                    errors.append(f"{edge} keep decision does not retain the original endpoint")
        if (not 0 <= bounds["start"] < bounds["end"] <= duration
                or duration - (bounds["end"] - bounds["start"]) > min(EDGE_BOUNDARY_VALIDATION["max_removed_seconds"], duration * EDGE_BOUNDARY_VALIDATION["max_removed_fraction"])):
            errors.append("proposed edge trim is outside safety bounds")
    return {**artifact, "trim_start": round(bounds["start"], 3), "trim_end": round(bounds["end"], 3),
            "validation_errors": errors, "status": "blocked" if errors else ("reviewed" if version == 2 else "legacy-reviewed")}


def trim_packet_evidence(original: Path, output: Path, requested_start: float) -> dict[str, Any]:
    """Measure copied packet provenance; this does not measure audible syllables."""
    def probe(path: Path) -> dict[str, Any]:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets", "-show_streams",
            "-show_data_hash", "sha256", "-show_entries",
            "packet=pts_time,duration_time,data_hash,side_data_list:stream=codec_name,sample_rate,start_time",
            "-of", "json", str(path)], check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    source, copied = probe(original), probe(output)
    source_packets, copied_packets = source.get("packets", []), copied.get("packets", [])
    if not source_packets or not copied_packets:
        raise RuntimeError("trim has no measurable audio packets")
    if source["streams"][0]["codec_name"] != copied["streams"][0]["codec_name"]:
        raise RuntimeError("trim changed the native codec")
    copied_hashes = [row.get("data_hash") for row in copied_packets]
    if not all(copied_hashes):
        raise RuntimeError("trim packet data hashes are missing")
    candidates = []
    for index, row in enumerate(source_packets):
        if row.get("data_hash") != copied_hashes[0] or abs(float(row["pts_time"]) - requested_start) > 0.25:
            continue
        section = source_packets[index:index + len(copied_packets)]
        if [item.get("data_hash") for item in section] == copied_hashes:
            candidates.append(section)
    if len(candidates) != 1:
        raise RuntimeError("trim packet provenance is ambiguous or does not match the source")
    matched = candidates[0]
    offsets = [float(left["pts_time"]) - float(right["pts_time"])
               for left, right in zip(matched, copied_packets)]
    if max(offsets) - min(offsets) > 0.003:
        raise RuntimeError("trim packet timestamps do not share a consistent source offset")
    return {"packet_source_offset": offsets[0], "packet_offset_spread": max(offsets) - min(offsets),
            "first_source_packet_pts": float(matched[0]["pts_time"]),
            "first_output_packet_pts": float(copied_packets[0]["pts_time"]),
            "source_first_packet_side_data": matched[0].get("side_data_list", []),
            "output_first_packet_side_data": copied_packets[0].get("side_data_list", []),
            "source_stream": source["streams"][0], "output_stream": copied["streams"][0],
            "matched_packets": len(copied_packets), "duration": gemini.duration_seconds(output)}


def apply_lossless_trim(song_dir: Path, artifact: dict[str, Any]) -> None:
    """Apply accepted v2 evidence from immutable originals, recoverably.

    The pending marker is a publication hold, not an applied claim. On resume,
    current files must match the initial or planned bytes; arbitrary external
    changes are preserved. Every output is prepared before public replacement.
    """
    import bhakti_model_routes as routes

    marker_path = song_dir / ".transcription" / "trim-applied.json"
    manifest_path = song_dir / ".transcription" / "trim-originals.json"
    archive_dir = song_dir / ".transcription" / "original-audio"
    existing = read_packet(marker_path) or {}
    if artifact.get("status") != "reviewed" or artifact.get("boundary_contract_version") != 2 or artifact.get("validation_errors"):
        raise RuntimeError("trim requires explicitly accepted current boundary evidence; legacy evidence needs review")
    normalized = normalize_trim_artifact(artifact)
    if normalized["validation_errors"] or normalized["status"] != "reviewed":
        raise RuntimeError("cannot apply blocked or uncertain trim review")
    start, end, duration = normalized["trim_start"], normalized["trim_end"], normalized["duration"]
    if artifact.get("trim_start") != start or artifact.get("trim_end") != end:
        raise RuntimeError("accepted trim bounds differ from retained observations")
    if existing.get("applied") and existing.get("application_version") != 2:
        raise RuntimeError("legacy applied trim has no verified original identity")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = read_packet(manifest_path)
    if manifest:
        sources = manifest.get("sources", [])
        if not sources or manifest.get("version") != 2:
            raise RuntimeError("invalid original audio identity manifest")
        if {row.get("src") for row in sources} != {row["src"] for row in listener_audio_sources(song_dir)}:
            raise RuntimeError("listener audio formats changed outside the trim transaction")
        for row in sources:
            name = row.get("src", "")
            if Path(name).name != name or not name.startswith("audio."):
                raise RuntimeError("invalid original audio identity path")
            original = archive_dir / name
            if not original.is_file() or digest(original) != row["sha256"]:
                raise RuntimeError("preserved original audio digest changed")
    else:
        sources = [{"src": row["src"], "sha256": digest(song_dir / row["src"])}
                   for row in listener_audio_sources(song_dir)]
        if not sources:
            raise RuntimeError("no original audio to trim")
    source_row = next((row for row in sources if row["src"] == normalized["source_audio"]), None)
    if source_row is None or source_row["sha256"] != normalized["source_sha256"]:
        raise RuntimeError("boundary review source identity changed")
    reviewed_source = archive_dir / source_row["src"] if manifest else song_dir / source_row["src"]
    if abs(gemini.duration_seconds(reviewed_source) - duration) > 0.01:
        raise RuntimeError("boundary review original duration changed")

    current = {row["src"]: digest(song_dir / row["src"]) for row in sources}
    for row in sources:
        name = row["src"]
        allowed = {row["sha256"]} if not existing or (not existing.get("applied") and existing.get("application_version") != 2) else set()
        if existing.get("application_version") == 2:
            expected = existing.get("outputs", {}).get(name, {}).get("sha256")
            if expected:
                allowed.add(expected)
            if existing.get("status") == "pending":
                allowed.add(existing.get("initial_assets", {}).get(name))
        if current[name] not in allowed:
            raise RuntimeError(f"listener audio changed outside the trim transaction: {name}")
    if (existing.get("status") in {"applied", "no-trim"} and existing.get("trim_start") == start
            and existing.get("trim_end") == end and existing.get("source_sha256") == normalized["source_sha256"]):
        return
    no_trim = start <= 0.001 and end >= duration - 0.001
    if no_trim and not manifest:
        routes.atomic_json(marker_path, {"application_version": 2, "applied": False, "status": "no-trim",
            "trim_start": start, "trim_end": end, "source_sha256": normalized["source_sha256"],
            "outputs": {name: {"sha256": value} for name, value in current.items()}})
        return
    if not manifest:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for row in sources:
            original = archive_dir / row["src"]
            if original.exists():
                if digest(original) != row["sha256"]:
                    raise RuntimeError("preserved original conflicts with current source")
            else:
                temporary = original.with_name(original.name + ".saving")
                shutil.copy2(song_dir / row["src"], temporary)
                if digest(temporary) != row["sha256"]:
                    raise RuntimeError("original audio archive copy failed verification")
                temporary.replace(original)
            with original.open("rb") as handle:
                os.fsync(handle.fileno())
        routes.atomic_json(manifest_path, {"version": 2, "sources": sources})
    work_dir = song_dir / ".transcription" / "trim-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for row in sources:
        original, output = archive_dir / row["src"], work_dir / row["src"]
        if no_trim:
            shutil.copy2(original, output)
        else:
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(original),
                            "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-map", "0:a:0", "-c", "copy",
                            "-avoid_negative_ts", "make_zero", str(output)], check=True)
        evidence = trim_packet_evidence(original, output, start)
        if evidence["duration"] <= 0 or abs(evidence["duration"] - (end - start)) > 0.25:
            raise RuntimeError("trim output duration does not match the retained interval")
        with output.open("rb") as handle:
            os.fsync(handle.fileno())
        outputs[row["src"]] = {**evidence, "sha256": digest(output)}
    pending = {"application_version": 2, "status": "pending", "applied": False,
               "trim_start": start, "trim_end": end, "source_sha256": normalized["source_sha256"],
               "removed_seconds": round(duration - (end - start), 3), "initial_assets": current, "outputs": outputs}
    routes.atomic_json(marker_path, pending)
    for row in sources:
        (work_dir / row["src"]).replace(song_dir / row["src"])
    for name, expected in outputs.items():
        if digest(song_dir / name) != expected["sha256"]:
            raise RuntimeError("trim output digest changed during application")
    routes.atomic_json(marker_path, {**pending, "status": "no-trim" if no_trim else "applied", "applied": not no_trim})


def stage_quality_failure(options: argparse.Namespace, detail: str, *, kind: str = "model_contract") -> None:
    """Classify an explicit model-output contract failure at its known origin."""
    if getattr(options, "unit_context", None) is not None:
        import bhakti_model_routes
        raise bhakti_model_routes.QualityFailure([{"kind": kind, "detail": detail}])
    raise RuntimeError(detail)


def stage_model_rows(response: Any, field: str, options: argparse.Namespace) -> list[dict[str, Any]]:
    """Validate model JSON containers before callers iterate or normalize them."""
    if not isinstance(response, dict) or not isinstance(response.get('packet'), dict):
        stage_quality_failure(options, f'{field}: response packet must be an object')
    rows = response['packet'].get(field)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        stage_quality_failure(options, f'{field}: model rows must be an array of objects')
    for row in rows:
        if field == 'glosses':
            words = row.get('word_glosses')
            if not isinstance(words, list) or any(not isinstance(word, dict) for word in words):
                stage_quality_failure(options, 'glosses: word_glosses must be an array of objects')
        if field == 'reviews' and 'issues' in row and not isinstance(row['issues'], list):
            stage_quality_failure(options, 'reviews: issues must be an explicit array')
    return rows


def stage_transport_context(options: argparse.Namespace) -> dict[str, Any]:
    """Optional persisted route context; never part of prompts or cache identity."""
    result = {}
    context = getattr(options, "unit_context", None)
    if context is not None:
        result["unit_context"] = context
    deadlines = [getattr(options, key, None) for key in ("unit_deadline_at", "semantic_deadline_at")]
    deadlines = [float(value) for value in deadlines if value is not None]
    if deadlines:
        result["deadline_at"] = min(deadlines)
    return result


def stage_call_timeout(options: argparse.Namespace) -> float:
    deadline = stage_transport_context(options).get("deadline_at")
    timeout = float(options.timeout)
    if deadline is not None:
        timeout = min(timeout, deadline - time.time())
    if timeout <= 0:
        raise RuntimeError("stage deadline exceeded before dispatch")
    return timeout


def ask(prompt: str, audio: Path | None, options: argparse.Namespace) -> dict[str, Any]:
    return gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=stage_call_timeout(options),
                       reasoning_effort="high", max_completion_tokens=65536, **stage_transport_context(options))


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
    source_first = bool(source.get("source_first_witness"))
    witness = source_witness.acquire(song_dir, song_dir.name, refresh=source_first) if source_first else None
    witness_lines = ([{"text": value} for value in (witness or {}).get("witness", {}).get("performance_additions", [])]
                     + list(witness.get("lines", [])) if witness else [])
    if source_first and not witness_lines:
        raise RuntimeError("source-first intake requires a complete registered textual witness")
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

        def run(job: tuple[dict[str, Any], Path], source_anchor: int | None = None) -> dict[str, Any]:
            segment, clip = job
            cache_path = cache_dir / f"segment-{segment['index']:03d}.json"
            cached = read_packet(cache_path)
            if (cached and cached.get("contract_version") == LONG_TRANSCRIPT_CONTRACT_VERSION
                    and cached.get("segment") == segment and isinstance(cached.get("response"), dict)):
                return cached
            source_first_context = ""
            if source_first:
                if source_anchor is None:
                    raise RuntimeError("source-first segment lacks a verified preceding witness anchor")
                # A segment can begin inside the preceding line. Retain a
                # narrow look-back for that overlap, then advance only from
                # the last source line the prior segment actually confirmed.
                start = max(0, source_anchor - 12)
                end = min(len(witness_lines), start + 140)
                candidates = [{"source_index": index, "source_text": witness_lines[index]["text"]}
                              for index in range(start, end)]
                source_first_context = f"""
SOURCE-CONTROLLED TRANSCRIPTION:
This is a complete performance of an identified Awadhi original-text witness. Do not freely transcribe, normalize, or reconstruct a lyric. Every returned `source_text` must copy one candidate line exactly, every returned `language` must be `Awadhi`, and returned lines must remain in candidate order. Select every candidate line audibly performed in this clip, including a line crossing an overlap; omit a candidate only when it is not heard. If the audible wording differs materially from every candidate, report that disagreement in `uncertainties` rather than inventing text.

Candidate witness lines:
{json.dumps(candidates, ensure_ascii=False)}
"""
            prompt = f"""Transcribe this complete devotional-song excerpt with extreme care. Listen through the entire clip repeatedly enough to avoid missing a single sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Do not translate. Do not infer unheard text. Mark uncertainty rather than guessing.

This is segment {segment['index']} of a longer recording. Its audio covers absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; its non-overlap core is {segment['core_start']:.3f}–{segment['core_end']:.3f}. Text in the overlap is intentionally duplicated and must still be transcribed. Identify the language and native script per line, including code-switching.

Source metadata is only a lead, never proof:
{json.dumps(source, ensure_ascii=False)}
{source_first_context}

Return strict JSON:
{{"lines":[{{"id":"segment-{segment['index']}-line-000","source_text":"","roman":"","language":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","partial":"none|leading|trailing","notes":""}}],"performance_order":[{{"line_id":"","occurrence":1}}],"uncertainties":[]}}"""
            response = None
            for attempt in range(2):
                try:
                    response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=stage_call_timeout(options),
                                           response_schema=segment_transcript_schema(), schema_name="bhakti_segment_transcript",
                                           reasoning_effort="high", max_completion_tokens=32768, **stage_transport_context(options))
                    break
                except RuntimeError as exc:
                    if getattr(options, "unit_context", None):
                        raise
                    if "required JSON packet" in str(exc):
                        # Retain the exact audio interval and schema, but
                        # normalize the container when a provider returns an
                        # empty structured response for the source AAC clip.
                        fallback = normalized_transcript_audio(
                            clip, destination / f"segment-{segment['index']:03d}-transcript-retry.mp3"
                        )
                        response = gemini.call(
                            options.model, gemini.key(), prompt, audio=fallback, timeout=stage_call_timeout(options),
                            response_schema=segment_transcript_schema(), schema_name="bhakti_segment_transcript",
                            reasoning_effort="high", max_completion_tokens=32768, **stage_transport_context(options))
                        break
                    if attempt:
                        raise
            if response is None:
                raise RuntimeError(f"segment {segment['index']} produced no transcription response")
            if source_first:
                returned = [str(line.get("source_text") or "") for line in response["packet"].get("lines", [])]
                cursor = 0
                indices: list[int] = []
                for text in returned:
                    match = next((item["source_index"] for item in candidates[cursor:]
                                  if str(item["source_text"]) == text), None)
                    if match is None:
                        raise RuntimeError(f"segment {segment['index']} returned text outside its witness window")
                    indices.append(match)
                    cursor = next(index for index, item in enumerate(candidates)
                                  if item["source_index"] == match) + 1
                if not indices:
                    raise RuntimeError(f"segment {segment['index']} selected no witness lines")
            item = {"contract_version": LONG_TRANSCRIPT_CONTRACT_VERSION,
                    "segment": segment, "response": response}
            if source_first:
                item["source_first_indices"] = indices
            write_json(cache_path, item)
            return item

        if source_first:
            responses = []
            anchor = 0
            for job in jobs:
                item = run(job, anchor)
                responses.append(item)
                anchor = max(item["source_first_indices"]) + 1
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
                responses = list(pool.map(run, jobs))
    packet = {"segmented": True, "source_first_witness": source_first,
              "segments": [{"segment": item["segment"], "transcript": item["response"]["packet"]}
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
        if getattr(options, "unit_context", None):
            raise
        if "required JSON packet" not in str(exc):
            raise
        with tempfile.TemporaryDirectory(prefix="bhakti-transcript-retry-") as temporary:
            fallback = normalized_transcript_audio(audio, Path(temporary) / "transcript.mp3")
            try:
                result = ask(prompt, fallback, options)
            except RuntimeError as fallback_exc:
                if getattr(options, "unit_context", None):
                    raise
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
    lines: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(packet.get("lines", [])):
        if not isinstance(line, dict) or not isinstance(line.get("id"), str) or not line["id"].strip():
            raise ValueError(f"segment line {index} has no nonempty string ID")
        if line["id"] in lines:
            raise ValueError(f"segment has duplicate line ID {line['id']!r}")
        for field in ("source_text", "roman"):
            if not isinstance(line.get(field), str) or not line[field].strip():
                raise ValueError(f"segment line {line['id']!r} has empty {field}")
        lines[line["id"]] = line
    ordered = []
    used = set()
    for index, entry in enumerate(packet.get("performance_order", [])):
        identifier = entry.get("line_id") if isinstance(entry, dict) else None
        if not isinstance(identifier, str) or identifier not in lines:
            raise ValueError(f"segment occurrence {index} references unknown line ID {identifier!r}")
        ordered.append(lines[identifier])
        used.add(identifier)
    if set(lines) - used:
        raise ValueError(f"segment lines absent from performance order: {sorted(set(lines) - used)}")
    return ordered


def source_lyric_signature(line: dict[str, Any]) -> str:
    """Compare native spelling without discarding meaningful vowel signs."""
    value = unicodedata.normalize("NFC", str(line.get("source_text") or "")).casefold()
    # These are alternative Hindi nasal spellings in adjoining audio audits.
    value = value.replace("ँ", "ं")
    return "".join(character for character in value
                   if character.isalnum() or unicodedata.category(character).startswith("M"))


def fragment_completed_by(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("partial") != "trailing" or right.get("partial") == "trailing":
        return False
    return any(bool(signature(left)) and signature(right).startswith(signature(left))
               for signature in (source_lyric_signature, lyric_signature))


def balanced_overlap(left: list[dict[str, Any]], right: list[dict[str, Any]], limit: int = 20) -> tuple[int, int, float]:
    best = (0, 0, 0.0)
    for left_count in range(1, min(limit, len(left)) + 1):
        for right_count in range(1, min(limit, len(right)) + 1):
            for signature in (source_lyric_signature, lyric_signature):
                left_text = "".join(signature(line) for line in left[-left_count:])
                right_text = "".join(signature(line) for line in right[:right_count])
                completes_fragment = (left_count == right_count == 1
                                      and fragment_completed_by(left[-1], right[0]))
                # A left model line can contain two complete right units.
                # Also allow an actual edge fragment to acquire its complete
                # counterpart; counts and confidence remain one comparison.
                if left_text and right_text and (left_text.endswith(right_text) or completes_fragment):
                    score = 1.0
                else:
                    if min(len(left_text), len(right_text)) < 15:
                        continue
                    # Unequal unit counts need exact aggregate evidence.
                    # Fuzzy character matches can borrow a new short lyric
                    # from a neighbouring line and silently erase it.
                    if left_count != right_count:
                        continue
                    score = 1.0
                    for left_line, right_line in zip(left[-left_count:], right[:right_count]):
                        left_unit, right_unit = signature(left_line), signature(right_line)
                        if not left_unit or not right_unit:
                            score = 0.0
                            break
                        similarity = difflib.SequenceMatcher(None, left_unit, right_unit, autojunk=False).ratio()
                        balance = min(len(left_unit), len(right_unit)) / max(len(left_unit), len(right_unit))
                        score = min(score, similarity * balance)
                if score > best[2]:
                    best = (left_count, right_count, score)
                    if score == 1.0:
                        return best
    return best


def normalized_language(value: str) -> str:
    key = value.strip().casefold()
    return {"hi": "Hindi", "hin": "Hindi", "hindi": "Hindi", "mr": "Marathi", "mar": "Marathi",
            "marathi": "Marathi", "sa": "Sanskrit", "san": "Sanskrit", "sanskrit": "Sanskrit",
            "pa": "Punjabi", "pan": "Punjabi", "punjabi": "Punjabi", "kn": "Kannada", "kan": "Kannada",
            "kannada": "Kannada", "awa": "Awadhi", "awadhi": "Awadhi", "bra": "Braj", "braj": "Braj", "raj": "Rajasthani",
            "rajasthani": "Rajasthani", "ta": "Tamil", "tam": "Tamil", "tamil": "Tamil",
            "te": "Telugu", "tel": "Telugu", "telugu": "Telugu", "or": "Odia", "ori": "Odia", "odia": "Odia",
            "bn": "Bengali", "ben": "Bengali", "bengali": "Bengali", "ml": "Malayalam", "mal": "Malayalam",
            "malayalam": "Malayalam", "fa": "Persian", "fas": "Persian", "per": "Persian", "persian": "Persian",
            "ur": "Urdu", "urd": "Urdu", "urdu": "Urdu"}.get(key, value.strip())


def assemble_audited_segment_occurrences(
    audited_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile adjoining raw evidence once, retaining occurrence provenance.

    A partial marker does not authorize deletion: performances may deliberately
    stop mid-line before an instrumental break. Only an edge fragment with a
    matching adjoining counterpart can be replaced or deduplicated. Confidence
    and removal counts always come from the same raw overlap comparison.
    """
    merged: list[dict[str, Any]] = []
    seams: list[dict[str, Any]] = []
    uncertainties: list[str] = []
    bounds: list[tuple[float, float] | None] = []
    for position, item in enumerate(audited_segments):
        segment = item["segment"]
        start, end = segment.get("clip_start"), segment.get("clip_end")
        valid_bounds = (all(isinstance(value, (int, float)) and not isinstance(value, bool)
                            and math.isfinite(value) for value in (start, end))
                        and start >= 0 and end > start)
        bounds.append((float(start), float(end)) if valid_bounds else None)
        if not valid_bounds:
            uncertainties.append(f"segment bounds {position} are missing, nonfinite, or invalid; occurrences retained without overlap deduplication")
        raw = ordered_segment_lines(item["audit"]["packet"])
        current = [{"line": line, "segment_position": position,
                    "segment_index": item["segment"]["index"],
                    "raw_occurrence_index": index, "raw_occurrence_count": len(raw)}
                   for index, line in enumerate(raw)]
        uncertainties.extend(str(value) for value in item["audit"]["packet"].get("uncertainties", []))
        if position == 0:
            merged.extend(current)
            continue
        previous = audited_segments[position - 1]
        previous_raw = ordered_segment_lines(previous["audit"]["packet"])
        left_bounds, right_bounds = bounds[position - 1], bounds[position]
        overlap_seconds = (min(left_bounds[1], right_bounds[1]) - max(left_bounds[0], right_bounds[0])
                           if left_bounds is not None and right_bounds is not None else None)
        left_count = right_count = 0
        score = 0.0
        if overlap_seconds is not None and overlap_seconds > 0:
            left_count, right_count, score = balanced_overlap(previous_raw, raw)
        candidate_left_count, candidate_right_count = left_count, right_count
        accepted = score >= 0.8
        replace_fragment = False
        if accepted:
            # This is the only case in which the older surface is incomplete.
            # Match the actual retained tail as well; never delete an unrelated
            # occurrence merely because a raw packet had a matching fragment.
            replace_fragment = (
                left_count == right_count == 1 and bool(merged)
                and fragment_completed_by(previous_raw[-1], raw[0])
                and lyric_signature(merged[-1]["line"]) == lyric_signature(previous_raw[-1])
            )
            if replace_fragment:
                merged.pop()
                right_count = 0
        elif overlap_seconds is not None and overlap_seconds > 0:
            uncertainties.append(f"segment seam {position - 1}/{position} overlap score is only {score:.3f}; all unmatched occurrences retained")
        seams.append({"left_segment": position - 1, "right_segment": position,
                      "left_overlap_occurrences": left_count if accepted else 0,
                      "right_overlap_occurrences": right_count if accepted else 0,
                      "score": round(score, 3), "overlap_seconds": overlap_seconds,
                      "replaced_edge_fragment": replace_fragment,
                      "candidate_left_count": candidate_left_count, "candidate_right_count": candidate_right_count})
        merged.extend(current[right_count:] if accepted else current)
    return {"occurrences": merged, "seams": seams, "uncertainties": uncertainties}


def merge_audited_segments(audited_segments: list[dict[str, Any]]) -> dict[str, Any]:
    assembly = assemble_audited_segment_occurrences(audited_segments)
    languages: list[str] = []
    for item in audited_segments:
        for line in item["audit"]["packet"].get("lines", []):
            language = normalized_language(str(line.get("language", "")))
            if language and language not in languages:
                languages.append(language)
    canonical: dict[str, dict[str, Any]] = {}
    order: list[dict[str, Any]] = []
    occurrence_counts: dict[str, int] = {}
    for occurrence in assembly["occurrences"]:
        line = occurrence["line"]
        signature = lyric_signature(line)
        if signature in canonical:
            previous = canonical[signature]
            def scripts(value: str) -> set[str]:
                return {unicodedata.name(character, "").split(" ")[0]
                        for character in value if character.isalpha()}
            # Folding Roman diacritics helps compare adjoining audio audits,
            # but must not identify distinct native words (मन/man vs मान/mān).
            # Keep the established cross-script matching behavior unchanged.
            native = source_lyric_signature(line)
            if (native != source_lyric_signature(previous)
                    and scripts(str(line.get("source_text", "")))
                    == scripts(str(previous.get("source_text", "")))):
                signature += "|native:" + native
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
                        json.dumps(assembly["seams"], separators=(",", ":"))],
            "uncertainties": assembly["uncertainties"]}


def audit_segment_merge_coverage(
    audited_segments: list[dict[str, Any]], merged_packet: dict[str, Any],
) -> dict[str, Any]:
    """Report cached merge losses without asserting that saved ASR is audible truth."""
    assembly = assemble_audited_segment_occurrences(audited_segments)
    expected = assembly["occurrences"]
    lines = {line["id"]: line for line in merged_packet.get("verified_lines", [])}
    actual = [lines.get(row.get("line_id"), {}) for row in merged_packet.get("performance_order", [])]
    # Native-script equality also covers different transliteration choices for
    # the same retained text; a spelling variation is not a missing occurrence.
    def key(line: dict[str, Any]) -> str:
        return source_lyric_signature(line) or lyric_signature(line)
    matcher = difflib.SequenceMatcher(None, [key(row["line"]) for row in expected],
                                     [key(line) for line in actual], autojunk=False)
    differences = []
    for operation, a, b, c, d in matcher.get_opcodes():
        if operation != "equal":
            differences.append({"operation": operation,
                                "expected_start": a, "expected_end": b,
                                "actual_start": c, "actual_end": d,
                                "expected_occurrences": expected[a:b], "actual_lines": actual[c:d]})
    return {"status": "mismatch" if differences else "uncertain" if assembly["uncertainties"] else "covered",
            "expected_occurrence_count": len(expected), "actual_occurrence_count": len(actual),
            "differences": differences, "seams": assembly["seams"],
            "uncertainties": assembly["uncertainties"]}


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
    assembly = assemble_audited_segment_occurrences(audited_segments)
    retained.extend(value for value in assembly["uncertainties"] if value not in retained)
    return retained


def audio_audit_clip_contract() -> dict[str, Any]:
    """Only settings consumed by the source-audit audio clip encoder."""
    return {"version": 1, "codec": "aac", "bitrate": "192k", "seek_precision": 3}


def audio_audit_request_contract(
    first: dict[str, Any], segment: dict[str, Any], *, witness=None,
    source_first: bool = False, source_context=None,
) -> dict[str, Any]:
    """Exact source-audio request, shared by cache identity and dispatch."""
    witness_context = source_witness.prompt_context(witness, first.get("lines", []))
    observation_prompt = ""
    if source_context is not None:
        observation_prompt = ("\nSOURCE OBSERVATION CONTEXT (competing source evidence, not accepted lyrics):\n"
            + json.dumps(source_context, ensure_ascii=False)
            + "\nCheck these alternatives and prior hearings against the complete attached audio. "
              "An omission hypothesis is not permission to insert unperformed text. "
              "Preserve uncertainty when readings cannot be distinguished.\n")
    source_first_context = ""
    if source_first:
        exact_lines = [{"source_text": line.get("source_text", "")}
                       for line in first.get("lines", [])]
        source_first_context = f"""
SOURCE-CONTROLLED AUDIT:
The first pass selected its text from an identified original witness. Do not rewrite, normalize, or replace its source text. Every returned `source_text` must exactly copy one item from the first-pass source list below. Use the audio only to confirm presence, order, overlap status, and an audible variant that must be reported as uncertainty.

First-pass source lines:
{json.dumps(exact_lines, ensure_ascii=False)}
"""
    prompt = f"""This is the required second transcription pass for one segment of a long devotional recording. Audit the entire first-pass transcript below against the complete attached segment. Use the first transcript as your working draft; do not start over.

Be extremely careful not to miss, hallucinate, reorder, or silently correct any sung, spoken, lead, response, invocation, refrain, pickup, repeated, or closing line. Preserve overlap text because local code reconciles it. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation. For Punjabi and other north-Indic readings use consistent IAST e/o, not mixed ē/ō; preserve nasalization and final orthographic vowels, and use only Latin-script letters in the roman field. Do not apply this e/o convention to Dravidian-language distinctions. Do not translate or estimate timestamps. Mark genuine uncertainty rather than guessing.

Segment audio: absolute source seconds {segment['clip_start']:.3f}–{segment['clip_end']:.3f}; core {segment['core_start']:.3f}–{segment['core_end']:.3f}.

FIRST TRANSCRIPT:
{json.dumps(first, ensure_ascii=False)}
{witness_context}
{source_first_context}{observation_prompt}

Return strict JSON:
{{"lines":[{{"id":"segment-{segment['index']}-line-000","source_text":"","roman":"","language":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","partial":"none|leading|trailing","notes":""}}],"performance_order":[{{"line_id":"","occurrence":1}}],"uncertainties":[]}}"""
    return {"version": 1, "prompt": prompt,
            "response_schema": segment_transcript_schema(), "schema_name": "bhakti_segment_audit",
            "reasoning_effort": "high", "max_completion_tokens": 32768,
            "clip": audio_audit_clip_contract()}


def audit_long_transcript(
    song_dir: Path, raw: dict[str, Any], audio: Path, options: argparse.Namespace,
    *, observation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    segments = raw["packet"]["segments"]
    source_first = bool(raw["packet"].get("source_first_witness"))
    if observation_context is not None:
        if (not isinstance(observation_context, dict)
                or set(observation_context) != {"witness", "source_context"}
                or not isinstance(observation_context["source_context"], dict)
                or observation_context["witness"] is not None and not isinstance(observation_context["witness"], dict)):
            raise ValueError("invalid explicit source observation context")
        # The caller binds and validates this snapshot before dispatch. Never
        # acquire a different witness while executing an identified observation.
        witness = observation_context["witness"]
    else:
        witness = source_witness.acquire(song_dir, song_dir.name)
    cache_dir = song_dir / ".transcription" / "pipeline" / "audit-segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-long-audit-") as temporary:
        destination = Path(temporary)
        jobs = []
        for item in segments:
            segment = item["segment"]
            request = audio_audit_request_contract(item["transcript"], segment,
                witness=witness, source_first=source_first,
                source_context=observation_context["source_context"] if observation_context is not None else None)
            codec = request["clip"]
            precision = codec["seek_precision"]
            clip = destination / f"segment-{segment['index']:03d}.m4a"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{segment['clip_start']:.{precision}f}",
                            "-i", str(audio), "-t", f"{segment['clip_end'] - segment['clip_start']:.{precision}f}", "-vn",
                            "-c:a", codec["codec"], "-b:a", codec["bitrate"], str(clip)], check=True)
            jobs.append((item, clip, request))

        def run(job: tuple[dict[str, Any], Path, dict[str, Any]]) -> dict[str, Any]:
            item, clip, request = job
            segment, first = item["segment"], item["transcript"]
            cached_path = cache_dir / f"segment-{segment['index']:03d}.json"
            cached = read_packet(cached_path)
            # A source-witness audit is specifically a new audio pass with
            # witness excerpts. Reusing a prior non-witness segment would
            # falsely report that verification happened.
            if cached and not options.source_witness_audit:
                return cached
            prompt = request["prompt"]
            last_error: RuntimeError | None = None
            for attempt in range(3):
                try:
                    response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=stage_call_timeout(options),
                                           response_schema=request["response_schema"], schema_name=request["schema_name"],
                                           reasoning_effort=request["reasoning_effort"], max_completion_tokens=request["max_completion_tokens"], **stage_transport_context(options))
                    if source_first:
                        allowed_text = {str(line.get("source_text") or "") for line in first.get("lines", [])}
                        invented = [str(line.get("source_text") or "") for line in response["packet"].get("lines", [])
                                    if str(line.get("source_text") or "") not in allowed_text]
                        if invented:
                            raise RuntimeError(f"source-first audit segment {segment['index']} rewrote witness text")
                    result = {"segment": segment, "first": first, "audit": response}
                    write_json(cached_path, result)
                    return result
                except RuntimeError as exc:
                    if getattr(options, "unit_context", None):
                        raise
                    last_error = exc
                    if "required JSON packet" in str(exc):
                        # The segment text itself may be perfectly clear while
                        # the provider emits an empty structured response for
                        # an AAC container.  Reuse the same bounded segment
                        # and schema with a normalized MP3 transport fallback;
                        # this is evidence-preserving, not a fresh transcript.
                        fallback = normalized_transcript_audio(
                            clip, destination / f"segment-{segment['index']:03d}-audit-retry.mp3"
                        )
                        response = gemini.call(
                            options.model, gemini.key(), prompt, audio=fallback, timeout=stage_call_timeout(options),
                            response_schema=request["response_schema"], schema_name=request["schema_name"],
                            reasoning_effort=request["reasoning_effort"], max_completion_tokens=request["max_completion_tokens"], **stage_transport_context(options))
                        result = {"segment": segment, "first": first, "audit": response}
                        write_json(cached_path, result)
                        return result
                    if "HTTP 502" not in str(exc) or attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
            raise last_error or RuntimeError("segment audit failed")

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            audited_segments = list(pool.map(run, jobs))
    if observation_context is not None:
        # Observation validation belongs to its routed caller. Do not pass raw
        # blank cues or malformed packets through the lexical merge first.
        return {"observation_only": True, "segment_audits": audited_segments,
                "source_first_witness": source_first, "resolved_model": options.model}
    merged = merge_audited_segments(audited_segments)
    if raw["packet"].get("source_first_witness"):
        source_responses = {item.get("segment", {}).get("index"): item
                            for item in raw.get("segment_responses", []) if isinstance(item, dict)}
        confirmed_seams = set()
        for index in range(1, len(segments)):
            left = source_responses.get(segments[index - 1]["segment"].get("index"), {})
            right = source_responses.get(segments[index]["segment"].get("index"), {})
            if set(left.get("source_first_indices", [])).intersection(right.get("source_first_indices", [])):
                confirmed_seams.add((index - 1, index))
        merged["uncertainties"] = [value for value in merged.get("uncertainties", [])
                                   if not any(str(value).startswith(f"segment seam {left}/{right}")
                                              for left, right in confirmed_seams)]
        expected = {str(value) for value in (witness or {}).get("witness", {}).get("performance_additions", [])}
        expected.update(str(item.get("text") or "") for item in (witness or {}).get("lines", []))
        line_by_id = {line["id"]: line for line in merged.get("verified_lines", [])}
        observed = [str(line_by_id.get(item.get("line_id"), {}).get("source_text") or "")
                    for item in merged.get("performance_order", [])]
        if any(item not in expected for item in observed):
            merged.setdefault("uncertainties", []).append(
                "source-first performance uses text outside the registered witness"
            )
    return {"packet": merged, "segment_audits": audited_segments, "source_first_witness": source_first,
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

Be extremely careful: correct every missed, hallucinated, duplicated, reordered, or misheard lyric. Preserve every audible performance occurrence in exact order, including lead pickups before answers and later returns. When the draft came from overlapping segments, reconcile duplicate overlap evidence without deleting genuine repeated performances. For Indic source text, retain the natural script and give a consistent scholarly ISO 15919/IAST-style romanization with accurate vowel length, retroflexion, aspiration, and language-appropriate pronunciation; do not mix plain and scholarly spellings. For Punjabi and other north-Indic readings use consistent IAST e/o, not mixed ē/ō; preserve nasalization and final orthographic vowels, and use only Latin-script letters in the roman field. Do not apply this e/o convention to Dravidian-language distinctions. Do not translate or estimate timestamps. If any content remains unclear, put it in uncertainties; do not silently guess.

Candidate transcript:
{json.dumps(raw['packet'], ensure_ascii=False)}
{witness_context}

Return strict JSON:
{{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"verified_lines":[{{"id":"stable-kebab-id","source_text":"","roman":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"stable-kebab-id","occurrence":1,"notes":""}}],"changes":[],"uncertainties":[]}}"""
    try:
        result = gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=stage_call_timeout(options),
                             response_schema=audited_transcript_schema(), schema_name="bhakti_audited_transcript",
                             reasoning_effort="high", max_completion_tokens=65536, **stage_transport_context(options))
    except RuntimeError as exc:
        if getattr(options, "unit_context", None):
            raise
        if "required JSON packet" not in str(exc):
            raise
        with tempfile.TemporaryDirectory(prefix="bhakti-audit-retry-") as temporary:
            fallback = normalized_transcript_audio(audio, Path(temporary) / "audit.mp3")
            try:
                result = gemini.call(options.model, gemini.key(), prompt, audio=fallback, timeout=stage_call_timeout(options),
                                     response_schema=audited_transcript_schema(), schema_name="bhakti_audited_transcript",
                                     reasoning_effort="high", max_completion_tokens=65536, **stage_transport_context(options))
            except RuntimeError as fallback_exc:
                if getattr(options, "unit_context", None):
                    raise
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


def reviewed_long_coarse_sequence(
    audited: dict[str, Any], occurrences: list[dict[str, Any]], duration: float,
    reviewed_source_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Route exact reviewed source aliases; ordinal hints are never audio onsets."""
    segments = audited.get("segment_audits", [])
    rebuilt = merge_audited_segments(segments)
    rebuilt_hash = hashlib.sha256(
        (json.dumps(rebuilt, ensure_ascii=False, indent=2) + "\n").encode()
    ).hexdigest()
    if reviewed_source_map.get("rebuilt_audit_sha256") != rebuilt_hash:
        raise ValueError("reviewed coarse map rebuilt source hash changed")
    raw_by = {row["id"]: row for row in rebuilt["verified_lines"]}
    if len(raw_by) != len(rebuilt["verified_lines"]):
        raise ValueError("duplicate rebuilt source ID")
    mapped_ids = set()
    raw_to_final = {}
    targets = {}
    for row in reviewed_source_map.get("mapping", []):
        raw_id = row.get("new_line_id")
        if raw_id not in raw_by or raw_id in mapped_ids:
            raise ValueError("duplicate or unknown reviewed coarse source ID")
        raw = raw_by[raw_id]
        raw_key = (raw["source_text"], raw["roman"])
        if (row.get("audited_source"), row.get("audited_roman")) != raw_key:
            raise ValueError("reviewed coarse source or roman changed")
        old_id = row.get("old_line_id")
        if old_id is None:
            target_id, target_key = "source-new-" + raw_id, raw_key
        else:
            baseline = row.get("baseline_line", {})
            target_id = old_id
            target_key = (baseline.get("source"), baseline.get("roman"))
        if not isinstance(target_id, str) or not target_id or any(
            not isinstance(value, str) or not value for value in target_key
        ):
            raise ValueError("invalid reviewed coarse target")
        if raw_key in raw_to_final and raw_to_final[raw_key] != target_id:
            raise ValueError("ambiguous reviewed coarse source pair")
        if target_id in targets and targets[target_id] != target_key:
            raise ValueError("conflicting reviewed coarse target baseline")
        raw_to_final[raw_key] = target_id
        targets[target_id] = target_key
        mapped_ids.add(raw_id)
    if mapped_ids != set(raw_by):
        raise ValueError("reviewed coarse map does not cover complete source")
    assembly = assemble_audited_segment_occurrences(segments)
    raw_occurrences = assembly["occurrences"]
    expected = []
    for raw in raw_occurrences:
        key = (raw["line"]["source_text"], raw["line"]["roman"])
        if key not in raw_to_final:
            raise ValueError("undeclared raw source pair in reviewed coarse order")
        expected.append(raw_to_final[key])
    actual = []
    for occurrence in occurrences:
        target_id = occurrence.get("ref")
        if target_id not in targets or (
            occurrence.get("source_text"), occurrence.get("roman")
        ) != targets[target_id]:
            raise ValueError("display source differs from reviewed coarse target")
        repeats = occurrence.get("repeats")
        if type(repeats) is not int or repeats < 1:
            raise ValueError("invalid reviewed coarse repeat count")
        actual.extend([target_id] * repeats)
    if actual != expected:
        raise ValueError("reviewed coarse complete performance order differs")
    result = []
    raw_index = 0
    for occurrence in occurrences:
        raw = raw_occurrences[raw_index]
        segment = segments[raw["segment_position"]]["segment"]
        span = float(segment["clip_end"]) - float(segment["clip_start"])
        point = (float(segment["clip_start"]) + span * raw["raw_occurrence_index"]
                 / max(1, raw["raw_occurrence_count"]))
        start = round(min(duration, max(point, result[-1]["start"] + 0.1 if result else 0.0)), 3)
        result.append({"occurrence_id": occurrence["occurrence_id"], "ref": occurrence["ref"],
                       "section": occurrence["section"], "repeats": occurrence["repeats"],
                       "start": start, "segment_index": int(segment["index"]),
                       "routing_only": True})
        raw_index += occurrence["repeats"]
    for index, row in enumerate(result):
        row["end"] = result[index + 1]["start"] if index + 1 < len(result) else duration
    return result


def long_coarse_sequence(
    audited: dict[str, Any], occurrences: list[dict[str, Any]], duration: float,
    *, reviewed_source_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if reviewed_source_map is not None:
        return reviewed_long_coarse_sequence(audited, occurrences, duration, reviewed_source_map)
    merged: list[tuple[dict[str, Any], float, int]] = []
    segment_audits = audited.get("segment_audits", [])
    assembly = assemble_audited_segment_occurrences(segment_audits)
    for occurrence in assembly["occurrences"]:
        segment = segment_audits[occurrence["segment_position"]]["segment"]
        span = float(segment["clip_end"]) - float(segment["clip_start"])
        # Routing only: raw ordinal positions are not claimed as syllable times.
        point = (float(segment["clip_start"]) + span * occurrence["raw_occurrence_index"]
                 / max(1, occurrence["raw_occurrence_count"]))
        merged.append((occurrence["line"], point, int(segment["index"])))
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
    if audited.get("source_first_witness"):
        if len(rebuilt) != len(occurrences):
            raise RuntimeError(
                "source-first long-audio coarse sequence differs from the audited performance order"
            )
        # Both sequences derive from the same source-controlled, independently
        # audited performance order. Pairing by position preserves a reviewed
        # audible spelling correction (for example bādhi vs. a witness's
        # bidhi) without allowing fuzzy text matching to drop that occurrence.
        pairs = list(enumerate(range(len(occurrences))))
    else:
        pairs = align_long_coarse_entries(occurrences, rebuilt)
    matched_actual = {actual_index for actual_index, _coarse_index in pairs}
    matched_coarse = {coarse_index for _actual_index, coarse_index in pairs}
    if len(matched_coarse) != len(rebuilt) and not audited.get("source_first_witness"):
        raise RuntimeError(
            "long-audio coarse reconciliation leaves "
            f"{len(rebuilt) - len(matched_coarse)} rebuilt occurrences unmatched"
        )
    if audited.get("source_first_witness") and len(matched_actual) != len(occurrences):
        raise RuntimeError(
            "source-first long-audio coarse reconciliation leaves "
            f"{len(occurrences) - len(matched_actual)} displayed occurrences unmatched"
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
            if type(raw["start"]) not in (int, float):
                raise ValueError
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
    performers = sorted({str(target.get("performer_context") or "").strip() for target in targets if str(target.get("performer_context") or "").strip()})
    performer_note = (f"\nPERFORMER CONTEXT (a listening cue only; never alter the lyric text or order): {', '.join(performers)}\n"
                      if performers else "")
    prompt = f"""The lyric transcription, order, repeat grouping, and occurrence IDs below are already final. Do not transcribe, correct, identify, reorder, group, or explain anything.
{performer_note}

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


def expanded_timing_targets(occurrences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Auxiliary repeat lookup; never split or rewrite the audited lyric itself."""
    expanded = []
    for occurrence in occurrences:
        repeats = occurrence.get('repeats', 1)
        if type(repeats) is not int or repeats < 1:
            raise ValueError('timing requires a positive audited repeat count')
        for index in range(repeats):
            expanded.append({**{key:value for key,value in occurrence.items() if key not in {'coarse_source_start','routing_only'}}, 'timing_id': f"{occurrence['occurrence_id']}-r{index + 1:02d}",
                             'repeat_index': index + 1, 'repeats': 1})
    return expanded


def validate_joint_timing_pass(region: dict[str, Any], packet: dict[str, Any], duration: float) -> dict[str, Any]:
    errors = []
    left, right = region['clip_start'], region['clip_end']
    if not (0 <= left < right <= duration and math.isfinite(duration)):
        errors.append('joint timing clip is outside the source duration')
    expected = [row['timing_id'] for row in expanded_timing_targets(region['target_occurrences'])]
    rows = packet.get('starts', [])
    if not isinstance(rows, list):
        return {'starts': [], 'validation_errors': errors + ['joint starts must be an array']}
    if [row.get('timing_id') if isinstance(row, dict) else None for row in rows] != expected:
        errors.append('joint timing IDs differ from exact expanded audited order')
    starts = []
    previous = -1.0
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or type(row.get('start')) not in (int, float):
                raise ValueError('non-numeric start')
            relative = float(row['start'])
            point = left + relative
            if not math.isfinite(relative) or not 0 <= relative < right-left or not 0 <= point < duration or point <= previous:
                raise ValueError('out of clip/duration or non-increasing start')
            if single_start_uncertainty_errors(row):
                raise ValueError('uncertain or incomplete first syllable')
            previous = point
            starts.append({'timing_id': row['timing_id'], 'start': round(point, 3)})
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f'joint start[{index}]: {exc}')
    return {'starts': starts if not errors else [], 'validation_errors': errors}


def joint_timing_consensus(region: dict[str, Any], first: dict[str, Any], second: dict[str, Any], duration: float) -> dict[str, Any]:
    passes = [validate_joint_timing_pass(region, packet, duration) for packet in (first, second)]
    return joint_consensus_from_measurements(region,passes)


def joint_consensus_from_measurements(region: dict[str, Any], passes: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [f'pass {index + 1}: {error}' for index, result in enumerate(passes) for error in result['validation_errors']]
    starts = []
    if not errors:
        for left, right in zip(passes[0]['starts'], passes[1]['starts']):
            if abs(left['start']-right['start']) > .5:
                errors.append(f"{left['timing_id']}: independent first-syllable measurements disagree")
            starts.append({'timing_id': left['timing_id'], 'start': round((left['start']+right['start'])/2, 3)})
    expanded = expanded_timing_targets(region['target_occurrences'])
    display = [{'occurrence_id': target['occurrence_id'], 'start': row['start']}
               for target, row in zip(expanded, starts) if target['repeat_index'] == 1]
    return {'starts': display if not errors else [], 'expanded_starts': starts if not errors else [],
            'validation_errors': errors, 'independent_passes': passes}


def joint_pair_evidence(
    report: dict[str, Any], *, expected_region: dict[str, Any],
    expected_fingerprint: str, duration: float,
) -> dict[str, Any]:
    """Recover agreeing pairs without accepting an otherwise failed region."""
    if (report.get("input_fingerprint") != expected_fingerprint
            or report.get("region") != expected_region):
        raise ValueError("joint evidence source/region fingerprint differs")
    passes = report.get("passes")
    if not isinstance(passes, list) or len(passes) != 2:
        raise ValueError("joint evidence requires two independent saved passes")
    checked = []
    for index, saved in enumerate(passes):
        region = {**expected_region, "clip_start": max(0., expected_region["clip_start"] - 10. * index)}
        if saved.get("region") != region:
            raise ValueError("joint evidence independent clip/context differs")
        validated = validate_joint_timing_pass(region, saved.get("response", {}).get("packet", {}), duration)
        if validated["validation_errors"]:
            raise ValueError("joint evidence has invalid full packet: " + "; ".join(validated["validation_errors"]))
        checked.append(validated["starts"])
    agreed, held = [], []
    targets = expanded_timing_targets(expected_region["target_occurrences"])
    for target, first, second in zip(targets, *checked):
        if abs(first["start"] - second["start"]) > .5:
            held.append(target["timing_id"])
        else:
            agreed.append({**target, "start": round((first["start"] + second["start"]) / 2, 3),
                           "measurements": [first["start"], second["start"]]})
    return {"agreed": agreed, "held_timing_ids": held}


def assemble_joint_pair_evidence(
    occurrences: list[dict[str, Any]], pairs: list[dict[str, Any]], duration: float,
) -> dict[str, Any]:
    """Require complete exact repeat-level evidence before deriving display times."""
    expanded = expanded_timing_targets(occurrences)
    by_id = {}
    for pair in pairs:
        timing_id = pair.get("timing_id")
        if not isinstance(timing_id, str) or timing_id in by_id:
            raise ValueError("duplicate/invalid retained timing ID")
        by_id[timing_id] = pair
    if set(by_id) != {row["timing_id"] for row in expanded}:
        raise ValueError("joint evidence does not cover every expanded performance")
    previous = -1.
    selected, display = [], []
    for target in expanded:
        pair = by_id[target["timing_id"]]
        if any(pair.get(key) != value for key, value in target.items()):
            raise ValueError("joint evidence source/order/identity changed")
        point = pair.get("start")
        if type(point) not in (int, float) or not math.isfinite(point) or not previous < point < duration:
            raise ValueError("joint evidence is non-increasing or outside duration")
        previous = point
        selected.append({"timing_id": target["timing_id"], "start": point})
        if target["repeat_index"] == 1:
            display.append({"occurrence_id": target["occurrence_id"], "start": point})
    sequence, errors, uncertain = timing_sequence_from_response(
        occurrences, {"starts": display, "uncertain_occurrence_ids": []}, duration)
    if errors or uncertain:
        raise ValueError("joint evidence display sequence invalid: " + "; ".join(errors))
    return {"sequence": sequence, "expanded_starts": selected}


def retained_timing_measurements(occurrences: list[dict[str, Any]], reports: list[dict[str, Any]], duration: float,
                                 *, require_consensus: bool = False) -> dict[str, float]:
    """Recover real audio measurements; old coarse-distance veto is not evidence.

    Caller must bind legacy reports to the exact source/audio identity before
    passing them here. Single-start candidate arrays alone are not provenance.
    """
    expected = {row['occurrence_id']: row for row in occurrences}
    windows: dict[str, list[float]] = {}
    singles: dict[str, float] = {}
    seen_windows = set()
    for report in reversed(reports):
        if report.get('kind') == 'single':
            continue
        key = report.get('cache_key', {})
        window_identity = json.dumps({'grid':report.get('grid'),'index':report.get('index'),
            'clip_start':report.get('clip_start'),'clip_end':report.get('clip_end'),'cache_key':key},
            sort_keys=True,ensure_ascii=False)
        if window_identity in seen_windows:
            continue
        seen_windows.add(window_identity)
        targets = key.get('targets', [])
        packet = report.get('response', {}).get('packet', {})
        rows = packet.get('starts', [])
        left, right = report.get('clip_start'), report.get('clip_end')
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)) or not 0 <= left < right <= duration:
            continue
        if not targets or [r.get('occurrence_id') for r in rows] != [r.get('occurrence_id') for r in targets]:
            continue
        uncertain = set(packet.get('uncertain_occurrence_ids', []))
        previous = -1.0
        for target, row in zip(targets, rows):
            occurrence_id = target['occurrence_id']
            current = expected.get(occurrence_id)
            if not current or any(target.get(field) != current.get(field) for field in ('source_text', 'roman', 'ref', 'repeats')):
                continue
            value = row.get('start')
            if type(value) not in (int, float) or not math.isfinite(value):
                continue
            point = left + value
            valid = 0 <= value < right-left and 0 <= point < duration and point > previous
            previous = max(previous, point)
            if not valid or occurrence_id in uncertain:
                continue
            if ('uncertainty' in row and single_start_uncertainty_errors(row)) or (value == 0 and row.get('onset_at_clip_start') is not True):
                continue
            windows.setdefault(occurrence_id, []).append(round(point, 3))
    for report in reports:
        occurrence_id = report.get('occurrence_id')
        if report.get('kind') != 'single' or occurrence_id not in expected:
            continue
        lower, upper = report.get('accepted_lower_bound'), report.get('accepted_upper_bound')
        left, right = report.get('clip_start'), report.get('clip_end')
        if left is None and isinstance(lower, (int, float)) and isinstance(upper, (int, float)) and upper > lower:
            left, right = max(0., lower-6.), min(duration, upper+6.)
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)) or not 0 <= left < right <= duration:
            continue
        points = []
        for attempt in report.get('attempts', []):
            packet = attempt.get('response', {}).get('packet', {})
            value = packet.get('start')
            if type(value) not in (int, float) or not math.isfinite(value) or packet.get('occurrence_id') != occurrence_id:
                continue
            point = left+value
            if not 0 <= value < right-left or not 0 <= point < duration or single_start_uncertainty_errors(packet):
                continue
            if abs(point-float(attempt.get('start', -1))) > .002:
                continue
            points.append(round(point, 3))
        corroborated = [point for point in points if corroborated_by_existing(point, windows.get(occurrence_id, []))]
        chosen = corroborated[-1] if corroborated else consensus_value(points)
        if chosen is not None:
            singles[occurrence_id] = round(chosen, 3)
    retained = {key: (consensus_value(values) if len(values)>1 else None if require_consensus else values[0]) for key, values in windows.items()}
    retained = {key: value for key, value in retained.items() if value is not None}
    retained.update(singles)
    return retained


def plan_joint_timing_regions(occurrences: list[dict[str, Any]], coarse: list[dict[str, Any]],
                              audited: dict[str, Any], duration: float, reports: list[dict[str, Any]]) -> dict[str, Any]:
    parents = (build_long_timing_chunks(audited, occurrences, coarse, duration) if audited.get('segment_audits') else
               [{'index':0,'clip_start':0.,'clip_end':duration,'target_indices':list(range(len(occurrences))),
                 'target_occurrences':copy.deepcopy(occurrences),'preceding_context':None,'following_context':None}])
    retained = retained_timing_measurements(occurrences, reports, duration)
    if not reports:
        return {'retained_starts': {}, 'regions': parents}
    bad = {i for i, row in enumerate(occurrences) if row['occurrence_id'] not in retained}
    for index in range(1, len(occurrences)):
        previous, current = (retained.get(occurrences[i]['occurrence_id']) for i in (index-1,index))
        if previous is not None and current is not None and previous >= current:
            bad.update((index-1,index))
    def source_key(row):
        return re.sub(r'[\s।॥|]+', ' ', unicodedata.normalize('NFC', row['source_text'])).strip()
    counts = {}
    for row in occurrences:
        key = source_key(row);counts[key] = counts.get(key, 0)+1
    ranges = []
    for parent in parents:
        seeds = sorted(bad.intersection(parent['target_indices']))
        if not seeds:
            continue
        first, last = seeds[0], seeds[-1]
        while first > 0 and counts[source_key(occurrences[first-1])] > 1:
            first -= 1
        while last+1 < len(occurrences) and counts[source_key(occurrences[last+1])] > 1:
            last += 1
        ranges.append((first,last,parent))
    merged = []
    for first,last,parent in ranges:
        if merged and first <= merged[-1][1]+1:
            old_first,old_last,old_parent=merged.pop();merged.append((old_first,max(last,old_last),old_parent))
        else:merged.append((first,last,parent))
    regions = []
    for first,last,parent in merged:
        preceding = occurrences[first-1] if first else None
        following = occurrences[last+1] if last+1 < len(occurrences) else None
        anchor = retained.get(preceding['occurrence_id']) if preceding else None
        left = max(0., anchor-10.) if anchor is not None else min(float(parent['clip_start']), float(coarse[first].get('segment_clip_start', parent['clip_start'])))
        # The following actual distinctive anchor supplies context only. If no
        # measured anchor exists, retain the full remaining audited audio.
        next_anchor = retained.get(following['occurrence_id']) if following else None
        right = min(duration, next_anchor+20.) if next_anchor is not None else duration
        targets = copy.deepcopy(occurrences[first:last+1])
        regions.append({'index':len(regions),'grid':'joint-context','clip_start':left,'clip_end':right,
                        'target_indices':list(range(first,last+1)), 'target_occurrences':targets,
                        'preceding_context':preceding,'following_context':following})
        for row in targets:retained.pop(row['occurrence_id'],None)
    return {'retained_starts':retained,'regions':regions}


def timing_input_identity(audio: Path, occurrences: list[dict[str, Any]], source_identity: dict[str, Any]) -> dict[str, Any]:
    return {'version': 2, 'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
            'source_identity': source_identity, 'ordered_occurrences': occurrences}


def run_joint_timing_unit(song_dir: Path, audio: Path, region: dict[str, Any], duration: float,
                          options: argparse.Namespace, source_identity: dict[str, Any]) -> dict[str, Any]:
    import bhakti_model_routes as routes
    identity = timing_input_identity(audio, region['target_occurrences'], source_identity)
    identity.update(region=region, duration=duration)
    fingerprint = hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    state_dir = song_dir / '.transcription' / 'pipeline' / 'joint-timing'
    unit_id = f"timing:{region['target_occurrences'][0]['occurrence_id']}:{region['target_occurrences'][-1]['occurrence_id']}"
    def execute(ctx):
        ctx.attempt_dir.mkdir(parents=True,exist_ok=True)
        expanded = expanded_timing_targets(region['target_occurrences'])
        rows = []
        passes = []
        for pass_index in range(2):
            # Independent calls use different cuts, identical audited order,
            # and no first-pass numbers. A wider second clip provides context.
            selected = {**region, 'clip_start': max(0.,region['clip_start']-10.*pass_index)}
            clip = ctx.attempt_dir / f'pass-{pass_index+1}.m4a'
            subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss',f"{selected['clip_start']:.3f}",
                            '-i',str(audio),'-t',f"{selected['clip_end']-selected['clip_start']:.3f}",
                            '-vn','-c:a','aac','-b:a','192k',str(clip)],check=True)
            task_role = ("PRIMARY ONSET MEASUREMENT" if pass_index == 0 else "INDEPENDENT FIRST-SYLLABLE AUDIT: re-listen and derive every start anew")
            prompt = f"""TASK: {task_role}.
Listen independently to this complete contextual excerpt. The transcript and order are fixed. Do not correct, normalize, regroup, drop or add lyrics. Only locate each exact first audible syllable, including every explicit consecutive repetition listed separately below. Embedded repetitions in a target's source text remain one target. Lead, response and pickup starts count. Return times relative to this clip, never a later repetition. If the requested initial syllable is cut off, masked, absent or ambiguous, declare uncertainty; do not guess.
SOURCE CLIP: {selected['clip_start']:.3f}–{selected['clip_end']:.3f} seconds.
PRECEDING CONTEXT ONLY: {json.dumps(region['preceding_context'],ensure_ascii=False)}
EXACT ORDERED TIMING TARGETS: {json.dumps(expanded,ensure_ascii=False)}
FOLLOWING CONTEXT ONLY: {json.dumps(region['following_context'],ensure_ascii=False)}
Return every timing_id exactly once in order, with start, uncertainty, and onset_at_clip_start. The last boolean may be true only when a COMPLETE initial syllable begins at the clip boundary. Already ongoing syllables are uncertain, not clear zero starts. Return JSON {{"starts":[{{"timing_id":"{expanded[0]['timing_id']}","start":0.0,"uncertainty":"","onset_at_clip_start":false}}]}}."""
            schema = {'type':'object','properties':{'starts':{'type':'array','minItems':len(expanded),'maxItems':len(expanded),
                'items':{'type':'object','properties':{'timing_id':{'type':'string'},'start':{'type':'number'},
                    'uncertainty':{'type':'string'},'onset_at_clip_start':{'type':'boolean'}},
                    'required':['timing_id','start','uncertainty','onset_at_clip_start'],'additionalProperties':False}}},
                'required':['starts'],'additionalProperties':False}
            kwargs = {'audio':clip,'timeout':ctx.call_timeout_seconds,'response_schema':schema,
                      'schema_name':'bhakti_joint_starts','reasoning_effort':'high','max_completion_tokens':65536}
            if ctx.transport_context is not None:
                kwargs.update(unit_context=ctx.transport_context,deadline_at=ctx.deadline_at)
            response = gemini.call(ctx.model,gemini.key(),prompt,**kwargs)
            report = {'region':selected,'response':response,'validation':validate_joint_timing_pass(selected,response['packet'],duration)}
            write_json(ctx.attempt_dir/f'pass-{pass_index+1}.json',report)
            passes.append(report)
        result=joint_consensus_from_measurements(region,[report['validation'] for report in passes])
        return {**result,'kind':'joint','region':region,'passes':passes,'input_fingerprint':fingerprint,'resolved_model':ctx.model}
    def validate(result):
        return [{'kind':'timing_disagreement','detail':error} for error in result['validation_errors']]
    deadline = getattr(options,'timing_deadline_at',None)
    if deadline is not None:
        return routes.run_unit(state_dir,unit_id,fingerprint,execute,validate,deadline_at=deadline,
                               base_model=gemini.batch_base_model(options.model),
                               pro_model=getattr(options,'pro_model',routes.PRO_MODEL))
    # Existing unbounded command remains Flash-only; escalation is opt-in.
    from types import SimpleNamespace
    attempt_dir=state_dir/fingerprint/'ordinary'
    cache=attempt_dir/'accepted.json'
    prior=read_packet(cache)
    if prior and not options.force and prior.get('input_fingerprint')==fingerprint:
        return prior
    result=execute(SimpleNamespace(model=gemini.batch_base_model(options.model),attempt_dir=attempt_dir,
                                  call_timeout_seconds=options.timeout,transport_context=None))
    write_json(attempt_dir/'candidate.json',result)
    if result['validation_errors']:
        raise RuntimeError('joint timing requires review: '+'; '.join(result['validation_errors']))
    write_json(cache,result)
    return result


def joint_region_fingerprint(audio_sha256, region, duration, source_identity):
    identity = {"version": 2, "audio_sha256": audio_sha256, "source_identity": source_identity,
                "ordered_occurrences": region["target_occurrences"], "region": region, "duration": duration}
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_joint_region_source(region, occurrences, duration):
    by_id = {row["occurrence_id"]: (index, row) for index, row in enumerate(occurrences)}
    indices = []
    for row in region.get("target_occurrences", []):
        original = by_id.get(row.get("occurrence_id"))
        clean = {key: value for key, value in row.items() if key not in {"coarse_source_start", "routing_only"}}
        if original is None or clean != original[1]:
            raise ValueError("continuation region changes audited source occurrence")
        indices.append(original[0])
    if not indices or indices != sorted(set(indices)) or region.get("target_indices") != indices:
        raise ValueError("continuation region changes target order/indices")
    left, right = region.get("clip_start"), region.get("clip_end")
    if (type(left) not in (int, float) or type(right) not in (int, float)
            or not 0 <= left < right <= duration):
        raise ValueError("continuation region has invalid audio bounds")
    for key, index in (("preceding_context", indices[0] - 1), ("following_context", indices[-1] + 1)):
        expected = occurrences[index] if 0 <= index < len(occurrences) else None
        if region.get(key) != expected:
            raise ValueError("continuation region context changes audited order")


def selected_joint_pairs(evidence, occurrences, duration, audio_sha256, source_identity):
    pairs = []
    for item in evidence:
        region = item["region"]
        validate_joint_region_source(region, occurrences, duration)
        fingerprint = joint_region_fingerprint(audio_sha256, region, duration, source_identity)
        if item.get("input_fingerprint") != fingerprint:
            raise ValueError("joint selection audio/source fingerprint differs")
        checked = joint_pair_evidence(item["report"], expected_region=region,
                                     expected_fingerprint=fingerprint, duration=duration)
        by_id = {row["timing_id"]: row for row in checked["agreed"]}
        selected = item.get("select_timing_ids")
        if (not isinstance(selected, list) or not selected or len(set(selected)) != len(selected)
                or not set(selected).issubset(by_id)):
            raise ValueError("joint selection includes missing or held measurements")
        pairs.extend(copy.deepcopy(by_id[timing_id]) for timing_id in selected)
    return pairs


def align_joint_continuation(song_dir, audio, occurrences, duration, options):
    declaration = options.timing_joint_continuation
    plan_path = Path(declaration["path"])
    plan_bytes = plan_path.read_bytes()
    plan_hash = hashlib.sha256(plan_bytes).hexdigest()
    if plan_hash != declaration.get("sha256"):
        raise ValueError("joint continuation plan hash changed")
    plan = json.loads(plan_bytes)
    audio_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    source_identity = options.timing_source_identity
    if (plan.get("version") != 1 or plan.get("audio_sha256") != audio_hash
            or plan.get("source_identity") != source_identity
            or plan.get("ordered_occurrences") != occurrences
            or plan.get("duration_seconds") != duration):
        raise ValueError("joint continuation changed frozen audio/source/order")
    evidence = []
    for saved in plan.get("retained", []):
        raw = Path(saved["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != saved.get("sha256"):
            raise ValueError("retained joint report hash changed")
        evidence.append({"region": saved["region"], "input_fingerprint": saved["input_fingerprint"],
                         "select_timing_ids": saved["select_timing_ids"], "report": json.loads(raw),
                         "original_report_sha256": saved["sha256"]})
    retained = selected_joint_pairs(evidence, occurrences, duration, audio_hash, source_identity)
    required = [row["timing_id"] for row in expanded_timing_targets(occurrences)]
    declared = [row["timing_id"] for row in retained]
    for pending in plan.get("pending", []):
        validate_joint_region_source(pending["region"], occurrences, duration)
        available = {row["timing_id"] for row in expanded_timing_targets(pending["region"]["target_occurrences"])}
        selected = pending.get("select_timing_ids")
        if not isinstance(selected, list) or not selected or not set(selected).issubset(available):
            raise ValueError("pending joint scope has invalid selected IDs")
        declared.extend(selected)
    if len(declared) != len(set(declared)) or set(declared) != set(required):
        raise ValueError("continuation must cover every repeat exactly once")
    retained_by_id = {row["timing_id"]: row for row in retained}
    previous = -1.
    for timing_id in required:
        if timing_id in retained_by_id:
            point = retained_by_id[timing_id]["start"]
            if point <= previous:
                raise ValueError("retained joint measurements are globally non-increasing")
            previous = point
    destination = song_dir / ".transcription/pipeline/joint-continuations" / plan_hash
    destination.mkdir(parents=True, exist_ok=True)
    receipt = {"plan_sha256": plan_hash, "audio_sha256": audio_hash,
               "source_identity": source_identity, "evidence": evidence, "pairs": retained}
    receipt_path = destination / "retained.json"
    if receipt_path.exists():
        if read_packet(receipt_path) != receipt:
            raise ValueError("durable retained joint receipt changed")
    else:
        write_json(receipt_path, receipt)
    for pending in plan.get("pending", []):
        region = pending["region"]
        report = run_joint_timing_unit(song_dir, audio, region, duration, options, source_identity)
        item = {"region": region, "input_fingerprint": joint_region_fingerprint(audio_hash, region, duration, source_identity),
                "select_timing_ids": pending["select_timing_ids"], "report": report}
        # Revalidate accepted output and selection before recording progress.
        selected_joint_pairs([item], occurrences, duration, audio_hash, source_identity)
        evidence.append(item)
        write_json(destination / "progress.json", {"plan_sha256": plan_hash, "evidence": evidence})
    assembled = assemble_joint_pair_evidence(
        occurrences, selected_joint_pairs(evidence, occurrences, duration, audio_hash, source_identity), duration)
    selection = {"kind": "joint-selection", "plan_sha256": plan_hash, "audio_sha256": audio_hash,
                 "source_identity": source_identity, "ordered_occurrences": occurrences,
                 "duration_seconds": duration, "evidence": evidence,
                 "expanded_starts": assembled["expanded_starts"]}
    write_json(destination / "accepted-selection.json", selection)
    return assembled["sequence"], [selection], []


def joint_selection_errors(selection, timing):
    try:
        occurrences = timing["ordered_occurrences"]
        duration = timing["duration_seconds"]
        if (selection["source_identity"] != timing["source_identity"]
                or selection["ordered_occurrences"] != occurrences or selection["duration_seconds"] != duration):
            raise ValueError("selected joint source/order/duration changed")
        pairs = selected_joint_pairs(selection["evidence"], occurrences, duration,
                                     selection["audio_sha256"], timing["source_identity"])
        assembled = assemble_joint_pair_evidence(occurrences, pairs, duration)
        if assembled["sequence"] != timing["sequence"] or assembled["expanded_starts"] != selection["expanded_starts"]:
            raise ValueError("selected timing differs from independently revalidated joint pairs")
        return []
    except (KeyError, TypeError, ValueError) as exc:
        return ["joint selection lacks complete independent evidence: " + str(exc)]


def align_long_segments(
    song_dir: Path, audio: Path, audited: dict[str, Any], occurrences: list[dict[str, Any]],
    coarse_sequence: list[dict[str, Any]], duration: float, options: argparse.Namespace,
    prior_refinements: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Jointly locate repeated regions before independent bounded verification."""
    if getattr(options, "timing_joint_continuation", None) is not None:
        return align_joint_continuation(song_dir, audio, occurrences, duration, options)
    plan=plan_joint_timing_regions(occurrences,coarse_sequence,audited,duration,prior_refinements or [])
    starts=dict(plan['retained_starts']);reports=list(prior_refinements or [])
    source_identity=getattr(options,'timing_source_identity',{})
    for region in plan['regions']:
        report=run_joint_timing_unit(song_dir,audio,region,duration,options,source_identity)
        reports.append(report)
        for row in report['starts']:starts[row['occurrence_id']]=row['start']
    packet={'starts':[{'occurrence_id':row['occurrence_id'],'start':starts.get(row['occurrence_id'])} for row in occurrences],
            'uncertain_occurrence_ids':[]}
    sequence,errors,uncertain=timing_sequence_from_response(occurrences,packet,duration)
    return sequence,reports,errors


def single_start_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "occurrence_id": {"type": "string"}, "start": {"type": "number"}, "uncertainty": {"type": "string"},
        "onset_at_clip_start": {"type": "boolean"}},
        "required": ["occurrence_id", "start", "uncertainty", "onset_at_clip_start"], "additionalProperties": False}


def single_start_uncertainty_errors(packet: dict[str, Any]) -> list[str]:
    """Declared doubt cannot become first-syllable evidence through agreement."""
    errors = []
    uncertainty = packet.get("uncertainty", "")
    if not isinstance(uncertainty, str) or uncertainty.strip().casefold() not in {"", "none", "no", "null", "n/a"}:
        errors.append("single start has unresolved uncertainty")
    if float(packet.get("start", -1)) == 0 and packet.get("onset_at_clip_start") is not True:
        errors.append("clip-boundary start lacks explicit complete-onset evidence")
    return errors


def timing_uncertainty_errors(timing: dict[str, Any]) -> list[str]:
    """Recheck selected cached evidence, allowing later clean repairs to supersede it."""
    errors = []
    for report in timing.get("refinements", []):
        if report.get("kind") == "joint-selection":
            errors.extend(joint_selection_errors(report, timing))
    if timing.get("uncertain_occurrence_ids"):
        errors.append("timing has unresolved uncertain occurrence IDs")
    selected = {item.get("occurrence_id"): item.get("start")
                for item in timing.get("sequence", [])}
    reports = {}
    joint_supported = set()
    joint_selected = set()
    for report in timing.get('refinements',[]):
        if report.get('kind') != 'joint' or len(report.get('passes',[])) != 2:
            continue
        joint_selected.update(row['occurrence_id'] for row in report.get('starts',[]) if selected.get(row.get('occurrence_id')) == row.get('start'))
        try:
            checked=[validate_joint_timing_pass(item['region'],item['response']['packet'],timing['duration_seconds']) for item in report['passes']]
            consensus=joint_consensus_from_measurements(report['region'],checked)
            if not consensus['validation_errors']:
                joint_supported.update(row['occurrence_id'] for row in consensus['starts'] if selected.get(row['occurrence_id']) == row['start'])
        except (KeyError,TypeError,ValueError):
            continue
    errors.extend(f'{occurrence_id}: selected joint start lacks clear independent evidence' for occurrence_id in sorted(joint_selected-joint_supported))
    for report in timing.get("refinements", []):
        if report.get("kind") != "single" or report.get("validation_errors"):
            continue
        occurrence_id = report.get("occurrence_id")
        if occurrence_id in joint_supported:
            continue
        if "sequence" in timing and occurrence_id not in selected:
            continue
        if occurrence_id in selected and report.get("start") != selected[occurrence_id]:
            continue
        reports[occurrence_id] = report
    for occurrence_id, report in reports.items():
        valid = []
        for attempt in report.get("attempts", []):
            if attempt.get("validation_errors"):
                continue
            packet = dict(attempt.get("response", {}).get("packet", {}))
            packet.setdefault("uncertainty", attempt.get("uncertainty_note", ""))
            if not single_start_uncertainty_errors(packet):
                valid.append(float(attempt["start"]))
        # Re-derive which clear measurements can support the selected start.
        # Old validators sometimes left rejected boundary doubts unmarked.
        corroborated = [value for value in valid
                        if report.get("candidate_is_evidence", True) and corroborated_by_existing(value, report.get("candidate_measurements", []))]
        chosen = None
        if corroborated:
            chosen = corroborated[-1]
        elif len(valid) >= 2 and max(valid) - min(valid) <= 0.5:
            chosen = median(valid)
        if chosen is None or abs(round(chosen, 3) - float(report["start"])) > 0.001:
            errors.append(f"{occurrence_id}: selected single start lacks clear agreeing evidence")
    return errors


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


def needs_targeted_long_recovery(report: dict[str, Any]) -> bool:
    """Whether an otherwise usable long-recording recovery merits one retry."""
    return (
        report.get("kind") == "single"
        and isinstance(report.get("occurrence_id"), str)
        and report.get("validation_errors") == ["single start lacks agreeing evidence"]
        and isinstance(report.get("candidate"), (int, float))
    )


def refine_single_start(
    audio: Path, occurrences: list[dict[str, Any]], index: int, candidate_measurements: list[float],
    duration: float, options: argparse.Namespace, destination: Path, *, clip_radius: float = 20.0,
    lower_bound: float | None = None, upper_bound: float | None = None,
    candidate_is_evidence: bool = True,
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
    performer_note = (f"\nPERFORMER CONTEXT (a listening cue only; never alter the lyric text or order): {target['performer_context']}\n"
                      if str(target.get("performer_context") or "").strip() else "")
    prompt = f"""The transcription, order, repeats, target ID, and approximate source location are already final. Do not transcribe, correct, identify, reorder, group, or explain anything.
{performer_note}

This attached clip is source seconds {clip_start:.3f}–{clip_end:.3f}. Return a time RELATIVE TO THIS CLIP.
PRECEDING CONTEXT: {json.dumps(previous, ensure_ascii=False) if previous else '(none)'}
TARGET: {json.dumps({**target, 'coarse_source_start': candidate}, ensure_ascii=False)}
FOLLOWING CONTEXT: {json.dumps(following, ensure_ascii=False) if following else '(none)'}

Return only the exact first audible syllable start of TARGET's first repetition. Do not choose another identical occurrence. Mark uncertainty rather than guessing. Set onset_at_clip_start=true only if the COMPLETE initial syllable audibly begins at the clip boundary; an already ongoing or cut-off syllable is uncertain, never a clear zero start. Otherwise set it false.

Return strict JSON only: {{"occurrence_id":"{target['occurrence_id']}","start":0.0,"uncertainty":"","onset_at_clip_start":false}}"""
    attempts: list[dict[str, Any]] = []
    for attempt in range(2):
        try:
            response = gemini.call(options.model, gemini.key(), prompt, audio=clip, timeout=options.timeout,
                                   response_schema=single_start_schema(), schema_name="bhakti_single_start",
                                   reasoning_effort="high", max_completion_tokens=4096)
            packet = response["packet"]
            if type(packet.get("start")) not in (int, float):
                raise ValueError("single start must be a finite number")
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
            # Long-segment coarse routing can place a repeated refrain in the
            # wrong local slot.  Treat its neighbour bracket as a routing hint,
            # not disqualifying evidence: two independent lyric-aware passes
            # must still agree before this point is accepted below.
            errors.extend(single_start_uncertainty_errors(packet))
            attempts.append({"attempt": attempt + 1, "start": round(point, 3), "uncertainty_note": uncertainty,
                             "response": response, "validation_errors": errors})
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            attempts.append({"attempt": attempt + 1, "error": str(exc), "validation_errors": ["unusable single response"]})
        valid = [item for item in attempts if not item["validation_errors"]]
        if candidate_is_evidence and valid and corroborated_by_existing(valid[-1]["start"], candidate_measurements):
            break
        if len(valid) >= 2 and max(item["start"] for item in valid) - min(item["start"] for item in valid) <= 0.5:
            break
    valid = [item for item in attempts if not item["validation_errors"]]
    errors: list[str] = []
    corroborated = [item for item in valid if candidate_is_evidence and corroborated_by_existing(item["start"], candidate_measurements)]
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
            "candidate_is_evidence": candidate_is_evidence,
            "clip_start": clip_start, "clip_end": clip_end,
            "accepted_lower_bound": lower_bound, "accepted_upper_bound": upper_bound,
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
    coarse_uncertain_ids: set[str] | None = None,
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
                                       if coarse_is_evidence and occurrence["occurrence_id"] not in (coarse_uncertain_ids or set()) else [])
        for index, occurrence in enumerate(occurrences)
    }
    for report in reports:
        # One malformed onset must not erase every valid onset returned in the
        # same structured window.
        for entry in report["starts"]:
            if entry["occurrence_id"] not in report.get("uncertain_ids",[]):
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
                if entry["occurrence_id"] not in report.get("uncertain_ids",[]):
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
                                                      measurements[occurrences[index]["occurrence_id"]] or [float(coarse_sequence[index]["start"])],
                                                      duration, options, destination,
                                                      candidate_is_evidence=bool(measurements[occurrences[index]["occurrence_id"]])), unresolved))
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
    cached_errors = timing_uncertainty_errors(existing) if existing else []
    if cached_errors and not audited.get("packet",{}).get("verified_lines"):
        raise RuntimeError("cached timing requires review and audited source before repair: " + "; ".join(cached_errors))
    packet = audited["packet"]
    occurrences = display_occurrences(packet)
    source = read_packet(song_dir / ".transcription" / "source.json") or {}
    performer = str(source.get("uploader") or source.get("channel") or "").strip()
    if performer:
        for occurrence in occurrences:
            occurrence["performer_context"] = performer
    if not packet.get("verified_lines") or not occurrences:
        raise RuntimeError("audited transcript lacks canonical lines or performance order")
    duration = gemini.duration_seconds(audio)
    source_identity = {'trim':read_packet(song_dir / '.transcription' / 'trim-applied.json') or {}}
    identity = timing_input_identity(audio,occurrences,source_identity)
    fingerprint = hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    options = copy.copy(options)
    options.timing_source_identity = identity
    exact = bool(existing and existing.get('input_fingerprint') == fingerprint)
    targeted = getattr(options,'timing_repair_occurrence_ids',None)
    if exact and not targeted and not cached_errors and not options.force and existing.get('publication_status') != 'blocked':
        return existing
    prior_refinements = []
    bound_legacy = False
    if existing:
        legacy = getattr(options,'timing_legacy_evidence_identity',{}) or {}
        old_bytes = target.read_bytes()
        old_hash = hashlib.sha256(old_bytes).hexdigest()
        fields=('occurrence_id','ref','source_text','roman','repeats','section')
        old_order=[{key:row.get(key) for key in fields} for row in existing.get('ordered_occurrences',[])]
        new_order=[{key:row.get(key) for key in fields} for row in occurrences]
        bound_legacy = (legacy.get('audio_sha256') == identity['audio_sha256'] and legacy.get('timing_sha256') == old_hash
                        and legacy.get('trim') == source_identity['trim'] and old_order == new_order)
        if exact or bound_legacy:
            prior_refinements=[row for row in existing.get('refinements',[]) if isinstance(row,dict)]
        archive=target.parent/'timing-history'/f'{old_hash}.json'
        if not archive.exists():
            archive.parent.mkdir(parents=True,exist_ok=True);archive.write_bytes(old_bytes)
    if targeted is not None:
        if not (existing and (exact or bound_legacy)):
            raise RuntimeError('targeted cached timing requires exact bound audio, trim, source order and prior timing')
        ids=[row['occurrence_id'] for row in occurrences]
        if (not isinstance(targeted,list) or not targeted or any(not isinstance(item,str) for item in targeted)
                or len(set(targeted)) != len(targeted) or not set(targeted).issubset(ids)):
            raise RuntimeError('targeted cached timing requires unique known occurrence IDs')
        evidence=retained_timing_measurements(occurrences,prior_refinements,duration,require_consensus=True)
        if not set(targeted).issubset(evidence):
            raise RuntimeError('targeted cached timing lacks independent clear agreeing measurements')
        previous=existing.get('sequence',[])
        if [row.get('occurrence_id') for row in previous] != ids:
            raise RuntimeError('targeted cached timing requires complete exactly ordered selected baseline')
        starts=[{'occurrence_id':row['occurrence_id'],'start':evidence[row['occurrence_id']] if row['occurrence_id'] in targeted else row['start']} for row in previous]
        unresolved=[item for item in existing.get('uncertain_occurrence_ids',[]) if item not in targeted]
        sequence,errors,uncertain=timing_sequence_from_response(occurrences,{'starts':starts,'uncertain_occurrence_ids':unresolved},duration)
        if uncertain:errors.append('unselected baseline contains unresolved timing uncertainty')
        result={**copy.deepcopy(existing),'input_fingerprint':fingerprint,'source_identity':identity,
                'duration_seconds':duration,'ordered_occurrences':occurrences,'sequence':sequence,
                'uncertain_occurrence_ids':uncertain,'validation_errors':errors,
                'publication_status':'blocked' if errors else 'review-required',
                'repair_scope':{'kind':'cached-independent-targeted-repair','target_occurrence_ids':targeted,
                    'retained_baseline_occurrence_ids':[item for item in ids if item not in targeted],
                    'retained_baseline_status':'unchanged; not freshly audio-certified'}}
        if errors:
            write_json(target.parent/'timing-candidates'/f'{fingerprint}.json',result)
        else:
            write_json(target,result)
        return result
    with tempfile.TemporaryDirectory(prefix="bhakti-timing-audio-") as temporary:
        model_audio = canonical_timing_audio(audio, Path(temporary) / "timing.m4a")
        if audited.get("segment_audits"):
            coarse_sequence = long_coarse_sequence(
                audited, occurrences, duration,
                reviewed_source_map=getattr(options, "timing_reviewed_source_map", None),
            )
            response = {"packet": {"source": "deterministic-segment-hints"}, "usage": {},
                        "resolved_model": "deterministic-segment-hints"}
            errors: list[str] = []
            uncertain: list[str] = []
        elif getattr(options,'timing_deadline_at',None) is not None:
            coarse_sequence = uniform_coarse_sequence(occurrences,duration)
            response = {'packet':{'source':'deterministic-routing'},'usage':{},'resolved_model':'deterministic-routing'}
            errors, uncertain = [], []
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
        if not errors and (audited.get("segment_audits") or getattr(options,"timing_deadline_at",None) is not None):
            sequence, refinements, refinement_errors = align_long_segments(
                song_dir, model_audio, audited, occurrences, coarse_sequence, duration, options,
                prior_refinements=prior_refinements,
            )
            errors.extend(refinement_errors)
        elif not errors:
            sequence, refinements, refinement_errors = refine_all_starts(
                model_audio, occurrences, coarse_sequence, duration, options,
                song_dir / ".transcription" / "pipeline" / "timing-windows",
                coarse_uncertain_ids=set(uncertain),
            )
            errors.extend(refinement_errors)
            if not refinement_errors and {row["occurrence_id"] for row in sequence} == {row["occurrence_id"] for row in occurrences}:
                uncertain = []
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
    result = {"input_fingerprint":fingerprint,"source_identity":identity,"duration_seconds": duration, "ordered_occurrences": occurrences, "response": response,
              "coarse_sequence": coarse_sequence, "refinements": refinements,
              "sequence": sequence, "uncertain_occurrence_ids": uncertain,
              "validation_errors": errors, "publication_status": "blocked" if errors else "review-required"}
    if errors:
        write_json(target.parent / "timing-candidates" / f"{fingerprint}.json", result)
    else:
        write_json(target, result)
    return result

def gloss_surface_errors(lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]]) -> list[str]:
    gloss_by_id = {row.get("id"): row for row in gloss_rows}
    errors: list[str] = []
    for line in lines:
        if str(line.get("kind") or "") == "instrumental":
            continue
        line_id = line.get("id", "<unknown>")
        words = gloss_by_id.get(line_id, {}).get("word_glosses", [])
        expected = bhakti_translation_policy.word_tokens(line)
        observed = [str(word.get("roman", "")) for word in words]
        if observed != expected:
            errors.append(f"{line_id} word gloss tokens differ from the complete ordered romanized source")
        for index, word in enumerate(words):
            if not str(word.get("gloss", "")).strip():
                errors.append(f"{line_id} word gloss {index} lacks a meaning")
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


def fresh_gloss_contract_errors(lines: list[dict[str, Any]],
                                gloss_rows: list[dict[str, Any]],
                                languages: list[str] | None = None) -> list[str]:
    """Fresh glosses have no locked English that could authorize preservation.

    Keep this separate from the legacy/public validator: generate-only must
    still accept previously reviewed, explicitly retained concepts.
    """
    errors = gloss_contract_errors(lines, gloss_rows)
    errors.extend(bhakti_translation_policy.sense_decision_errors(lines, gloss_rows, languages))
    if preserved_term_registry().get("defaultTreatment") == "translate_contextually":
        for row in gloss_rows:
            for index, word in enumerate(row.get("word_glosses", [])):
                if word.get("preserve_in_english") is True:
                    errors.append(f"{row.get('id')} fresh gloss {index} cannot preserve a concept without locked English")
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
    # Cleaning may remove punctuation-only entries, never relabel lexical
    # evidence. A changed surface needs a fresh judgment, even at equal length.
    return clean_gloss_rows(rows)


def gloss(song_dir: Path, audited: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "04-glosses.json"
    lines = audited["packet"].get("verified_lines", [])
    languages = audited["packet"].get("metadata", {}).get("languages")
    support = bhakti_lexical_support.prepare_options(options, lines, languages)
    policy = semantic_stage_policy(options)
    fingerprint = text_stage_fingerprint("gloss", options.model,
                                         {"lines": lines, "languages": languages}, policy)
    existing = read_packet(target)
    if (existing and existing.get("fingerprint") == fingerprint and not options.force
            and existing.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
            and not fresh_gloss_contract_errors(lines, existing.get("packet", {}).get("glosses", []), languages)
            and not bhakti_lexical_support.support_decision_errors(support, existing.get("packet", {}).get("glosses", []))):
        return existing
    def prompt_for(batch: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
        term_registry = preserved_term_registry()
        return f"""Create a literal word-by-word reading of the TARGET audited devotional lyrics. Work line by line and use the surrounding song context.

When a source line supplies lexical_tokens, copy that validated existing displayed word division exactly: create one word_gloss per supplied token in its exact order, including supported subdivisions within a written compound. Otherwise create exactly one word_gloss entry for each lexical whitespace-delimited surface token in the supplied roman line, in the identical order. Omit a token made entirely of punctuation, such as `।`, `॥`, a dash, or an ellipsis; punctuation remains visible but is not a word or hover target. Never substitute an underlying dictionary form or invent a new division. Give the contextually correct primary sense first. A gloss is semantic evidence, not an English draft: do not bake a clumsy phrase such as “cast a glance of mercy” into a token gloss when the phrase-level meaning is “look upon someone with mercy.” Put phrase meaning and idiom in the semantic frame instead. Use established English words or transparent source-supported compounds. Never present a franchise-specific fictional coinage such as `adamantium`, `vibranium`, or `mithril` as ordinary English. Rare but attested English such as `adamantine` is valid when it is the precise supported sense.

Before any later translation, explicitly reconstruct the semantic frame: who is acting or experiencing; the action or state; its patient or complement; modifiers; negation or modality; the exact literal image and agency; any established idiom; and how the line connects grammatically to its neighbors. Preserve personification and unusual agency rather than normalizing them. Distinguish a suffered or resultant state from a self-caused act: if the line says the speaker is broken, undone, struck, or seized, do not reinterpret it as the speaker actively breaking, undoing, striking, or seizing themself. Do not replace one metaphor with another: if a feeling “takes hold,” do not relabel it as kindling or stirring. Preserve a spatial word directly—“inside” remains “inside”—rather than upgrading it to “deep within” unless the source actually expresses depth. Represent reduplication as emphasis or repetition without inventing a new image. Expand relational objects when English requires their complement—a hem is the hem of a garment. Distinguish culturally specific objects precisely, such as an alms bag rather than a generic satchel, and palm/open palm rather than an abstract “hand” when the source requires it. For `raham nazar`, record the phrase-level meaning “look upon someone with mercy,” never “cast a glance.”

Explain internal morphemes inside the token's `gloss` or `grammar_note`. Give a short grammar note for ellipsis, agreement, sandhi, compounds, or syntax. Choose the contextually supported sense of a polysemous word; do not call ordinary dictionary polysemy uncertain. Use uncertainty only when the audited lyric itself remains genuinely unresolved. Do not write a fluent English sentence in this stage.

For `nām`, gloss the contextual sense as “name,” “divine name,” or “appellation”; never repeat the visible term. For a proper name, state the evidenced identity or relationship rather than merely repeating it: in a Rāma context `Janaka` is Sītā’s father, the king of Mithilā.

Do not collapse South Asian social terminology into the single English word “caste.” A jāti or jñātī is ordinarily a local birth, kin, or occupational community; gloss it as community, clan, kin group, or occupational group as the line warrants. Varṇa is a distinct broad fourfold normative social order; name that distinction explicitly when it matters. Preserve a source phrase that contrasts these terms rather than treating them as synonyms.

Translate ordinary words and philosophical concepts into precise English, using a short contextual phrase even when a concept is listed in the registry. A matching `concept_key` may identify a concept for bookkeeping; it does not require IAST in English. Set `preserve_in_english=false` for newly reconstructed glosses. `preserve_in_english=true` is reserved for explicitly supplied, locked English that retains that concept; no locked English is supplied at this gloss stage. Proper names are separate from concept preservation: retain genuine names in English and explain their evidenced identity or relationship in the hover. The hover must contain the meaning only: never repeat the visible Roman term before its explanation. Write `intellect; faculty of discernment`, not `buddhi (intellect; faculty of discernment)`; write `spiritual teacher`, not `guru / spiritual teacher`. For a divine epithet, explain its operative meaning rather than merely spelling the same title again. Build a local glossary while processing this song: when the same displayed token recurs in the same grammatical and devotional role, reuse its most specific established explanation verbatim. A changed explanation is allowed only when the local syntax or imagery materially changes; say why in that line's grammar note. In particular, bare “illusion” is not an adequate contextual explanation for `māyā`. For ordinary words and proper names, set `concept_key` to the empty string and `preserve_in_english=false`. Do not invent new registry entries. Genuine unresolved source or semantic conflict belongs in uncertainty.

{bhakti_translation_policy.guidance(batch, languages=languages, context_lines=getattr(options, "semantic_full_source", lines), performance_order=getattr(options, "semantic_performance_order", audited["packet"].get("performance_order", [])))}{bhakti_lexical_support.prompt(support, [line['id'] for line in batch], 'gloss')}

For every lexical word, return exactly one sense_decisions item in word-index order.
Copy word_index and roman from tokens in COMPACT LEXICAL EVIDENCE.
Use each token’s candidate_entry_ids to locate the complete entries and all their senses.
Account for every supplied
(entry_id, sense_id) exactly once in chosen or rejected. Explain rejected senses,
the chosen contextual meaning (including any deliberate simultaneous senses), and
the grammatical role. dictionary_supported requires a selected supplied sense;
contextual_inference uses no selected supplied sense and explains the grammar/context
when no entry fits or no dictionary is supplied for this language. Do not invent IDs.
missing_evidence means you cannot resolve the meaning, not a mere dictionary gap.
The primary word gloss must express the choice, and the semantic frame must agree.
These are your proposed interpretations, awaiting independent review.

CURATED PRESERVED-TERM REGISTRY:
{json.dumps(term_registry, ensure_ascii=False)}

{semantic_repair_prompt(options)}

TARGET LYRICS (return these IDs only):
{json.dumps([{**line, "surface_tokens": bhakti_translation_policy.word_tokens(line)}
            for line in batch], ensure_ascii=False)}

NEARBY CONTEXT (do not return these IDs unless also targets):
{json.dumps(context, ensure_ascii=False)}

Return strict JSON:
{{"glosses":[{{"id":"canonical-id","word_glosses":[{{"roman":"exact token","gloss":"short contextual meaning","concept_key":"","preserve_in_english":false}}],"semantic_frame":{{"agent":"","action_or_state":"","patient_or_complement":"","modifiers":"","negation_or_modality":"","literal_image_and_agency":"","idiom_or_phrase":"","cross_line_relation":""}},"grammar_note":"","uncertainty":"","sense_decisions":[{{"word_index":0,"roman":"exact token","evidence_status":"contextual_inference","chosen":[],"rejected":[],"contextual_reason":"source/context reason","grammatical_role":"role in clause"}}]}}]}}"""
    schema = {"type": "object", "properties": {"glosses": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"}, "word_glosses": {"type": "array", "items": {"type": "object", "properties": {
                "roman": {"type": "string"}, "gloss": {"type": "string"},
                "concept_key": {"type": "string"}, "preserve_in_english": {"type": "boolean"}},
                "required": ["roman", "gloss", "concept_key", "preserve_in_english"], "additionalProperties": False}},
            "semantic_frame": {"type": "object", "properties": {
                field: {"type": "string"} for field in SEMANTIC_FRAME_FIELDS},
                "required": list(SEMANTIC_FRAME_FIELDS), "additionalProperties": False},
            "grammar_note": {"type": "string"}, "uncertainty": {"type": "string"},
            "sense_decisions": bhakti_translation_policy.sense_decision_schema()},
        "required": ["id", "word_glosses", "semantic_frame", "grammar_note", "uncertainty", "sense_decisions"], "additionalProperties": False}}},
        "required": ["glosses"], "additionalProperties": False}
    # Gloss packets contain a word map and eight-field semantic frame per
    # source line.  Above forty lines the single structured response becomes
    # needlessly large and can stall before producing a recoverable cache.
    if len(lines) <= 40:
        result = gemini.call(options.model, gemini.key(), prompt_for(lines, []), audio=None, timeout=stage_call_timeout(options),
                                       response_schema=bhakti_lexical_support.extend_schema(schema, support, "gloss"), schema_name="bhakti_word_glosses",
                             reasoning_effort="high", max_completion_tokens=65536, **stage_transport_context(options))
        semantic_write_json(target.parent / 'gloss-candidate.json', result)
        result["packet"]["glosses"] = normalize_gloss_rows(lines, stage_model_rows(result, 'glosses', options))
    else:
        batch_size = int(getattr(options, "gloss_batch_size", 40) or 40)
        if batch_size < 1:
            raise RuntimeError("gloss_batch_size must be positive")
        batches = [lines[index:index + batch_size] for index in range(0, len(lines), batch_size)]
        cache_dir = song_dir / ".transcription" / "pipeline" / (
            "gloss-batches" if batch_size == 40 else f"gloss-batches-{batch_size}"
        )
        cache_dir.mkdir(parents=True, exist_ok=True)

        def run(index: int) -> dict[str, Any]:
            batch = batches[index]
            expected = [line["id"] for line in batch]
            cache_path = cache_dir / f"batch-{index:03d}.json"
            start = index * batch_size
            def batch_fingerprint(target_lines: list[dict[str, Any]], absolute_start: int) -> str:
                return text_stage_fingerprint("gloss-batch", options.model,
                    {"lines": target_lines,
                     "context": nearby_text_context(lines, absolute_start, len(target_lines)),
                     "languages": languages}, policy)
            batch_identity = batch_fingerprint(batch, start)
            cached = read_packet(cache_path)
            if (cached and cached.get("target_ids") == expected
                    and cached.get("fingerprint") == batch_identity and not options.force):
                cached_rows = cached.get("response", {}).get("packet", {}).get("glosses", [])
                if (cached.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
                        and not fresh_gloss_contract_errors(batch, cached_rows, languages)):
                    return cached

            def request(target_lines: list[dict[str, Any]], absolute_start: int, label: str) -> dict[str, Any]:
                target_ids = [line["id"] for line in target_lines]
                context = nearby_text_context(lines, absolute_start, len(target_lines))
                response = gemini.call(options.model, gemini.key(), prompt_for(target_lines, context), audio=None,
                                       timeout=stage_call_timeout(options),
                                       response_schema=bhakti_lexical_support.extend_schema(schema, support, "gloss"),
                                       schema_name="bhakti_word_gloss_batch", reasoning_effort="high",
                                       max_completion_tokens=65536,
                                       max_attempts=getattr(options, "max_attempts", 6), **stage_transport_context(options))
                # Preserve a private candidate before normalization so a
                # deterministic mapping rejection can be repaired without
                # paying to regenerate otherwise sound lexical work.
                write_json(cache_dir / f"candidate-{label.replace('.', '-')}.json", {
                    "target_ids": target_ids, "response": response,
                })
                response["packet"]["glosses"] = normalize_gloss_rows(
                    target_lines, stage_model_rows(response, 'glosses', options)
                )
                returned = [row.get("id") for row in response["packet"].get("glosses", [])]
                if returned != target_ids:
                    stage_quality_failure(options, f"gloss batch {label} returned IDs out of order or incomplete")
                mapping_errors = fresh_gloss_contract_errors(target_lines, response["packet"]["glosses"], languages)
                if mapping_errors:
                    stage_quality_failure(options, f"gloss batch {label} violates surface-token mapping: {mapping_errors[:3]}")
                return response

            if len(batch) > 20:
                children = []
                for child_index, offset in enumerate(range(0, len(batch), 20)):
                    child = batch[offset:offset + 20]
                    child_ids = [line["id"] for line in child]
                    child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                    child_packet = read_packet(child_path)
                    child_identity = batch_fingerprint(child, start + offset)
                    if not (child_packet and child_packet.get("target_ids") == child_ids
                            and child_packet.get("fingerprint") == child_identity
                            and child_packet.get("gloss_contract_version") == GLOSS_CONTRACT_VERSION
                            and not fresh_gloss_contract_errors(child, child_packet.get("response", {}).get("packet", {}).get("glosses", []), languages)
                            and not options.force):
                        child_packet = {
                            "target_ids": child_ids,
                            "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                            "fingerprint": child_identity,
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
                          "fingerprint": batch_identity, "response": response, "child_batches": children}
            else:
                packet = {"target_ids": expected, "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                          "fingerprint": batch_identity, "response": request(batch, start, str(index))}
            write_json(cache_path, packet)
            return packet

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(max(1, int(getattr(options, "gloss_workers", 2) or 2)), len(batches))) as pool:
            packets = list(pool.map(run, range(len(batches))))
        result = {"packet": {"glosses": [row for packet in packets
                                           for row in packet["response"]["packet"]["glosses"]]},
                  "batch_responses": packets, "gloss_contract_version": GLOSS_CONTRACT_VERSION,
                  "resolved_model": options.model}
    errors = fresh_gloss_contract_errors(lines, result.get("packet", {}).get("glosses", []), languages)
    errors.extend(bhakti_lexical_support.support_decision_errors(support, result.get("packet", {}).get("glosses", [])))
    if errors:
        stage_quality_failure(options, f"gloss output violates source contract: {errors[:3]}")
    result["gloss_contract_version"] = GLOSS_CONTRACT_VERSION
    result["sense_languages"] = languages
    result["fingerprint"] = fingerprint
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
            "material_choice": {"type": "string"}, "reason": {"type": "string"}, "issues": bhakti_semantic_repair.issue_schema()},
        "required": ["issues", "id", "passes", "human_review_recommended", "agency_preserved", "imagery_preserved",
                     "all_meaning_accounted_for", "unsupported_additions", "material_choice", "reason"],
        "additionalProperties": False}}}, "required": ["reviews"], "additionalProperties": False}


def select_translation_review_rows(
    rows: Any, target_ids: list[str], context_ids: list[str],
) -> list[dict[str, Any]]:
    """Project unique semantic review records onto their explicit requested IDs.

    Context records may be returned by a model, but never become target evidence
    for another request. This is not an audio or performance-order repair.
    """
    if (not isinstance(target_ids, list) or not target_ids
            or any(not isinstance(item, str) or not item for item in target_ids)
            or len(target_ids) != len(set(target_ids))):
        raise ValueError("translation review target IDs must be unique nonempty strings")
    if (not isinstance(context_ids, list)
            or any(not isinstance(item, str) or not item for item in context_ids)):
        raise ValueError("translation review context IDs must be nonempty strings")
    if not isinstance(rows, list):
        raise ValueError("translation reviews must be an array")
    known = set(target_ids) | set(context_ids)
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("translation review row must have a nonempty string ID")
        line_id = row["id"]
        if line_id in by_id:
            raise ValueError(f"duplicate translation review ID: {line_id}")
        if line_id not in known:
            raise ValueError(f"unknown translation review ID: {line_id}")
        by_id[line_id] = row
    missing = [line_id for line_id in target_ids if line_id not in by_id]
    if missing:
        raise ValueError(f"missing translation review target IDs: {missing}")
    return [by_id[line_id] for line_id in target_ids]


def translation_reading_context(lines, gloss_rows, translation_rows, target_ids, *,
                                performance_order=(), full_evidence=()):
    """Bounded current English/gloss context, never additional output targets.

    Target evidence wins over older full-context duplicates. All selected records
    must exist; missing context and overflow fail before any reviewer dispatch.
    """
    evidence = {}
    explicit_refs = set()
    for row in full_evidence:
        if not isinstance(row, dict) or not isinstance(row.get("source"), dict):
            raise ValueError("translation context record lacks source")
        line_id = row["source"].get("id")
        if not isinstance(line_id, str) or not line_id:
            raise ValueError("translation context source lacks ID")
        if row.get("explicit_reference"):
            explicit_refs.add(line_id)
        value = {key: copy.deepcopy(row.get(key)) for key in ("source", "gloss", "draft")}
        if (line_id in evidence and evidence[line_id] != value
                and line_id not in {line.get("id") for line in lines}):
            raise ValueError("translation context has conflicting duplicate evidence")
        evidence[line_id] = value
    def indexed(rows, label):
        found = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in found:
                raise ValueError("translation context has invalid/duplicate " + label)
            found[row["id"]] = row
        return found
    source_by_id = indexed(lines, "source")
    gloss_by_id = indexed(gloss_rows, "gloss")
    draft_by_id = indexed(translation_rows, "draft")
    for line_id, line in source_by_id.items():
        evidence[line_id] = {"source": copy.deepcopy(line),
            "gloss": copy.deepcopy(gloss_by_id.get(line_id)),
            "draft": copy.deepcopy(draft_by_id.get(line_id))}
    if (not isinstance(target_ids, list) or len(target_ids) != len(set(target_ids))
            or any(line_id not in evidence for line_id in target_ids)):
        raise ValueError("translation context has invalid target IDs")
    order_basis = "performed-order" if performance_order else "definition-order-unverified"
    raw_order = performance_order or [{"line_id": line_id} for line_id in evidence]
    occurrences = []
    counts = {}
    for event in raw_order:
        if not isinstance(event, dict):
            raise ValueError("translation context order event is invalid")
        line_id = event.get("line_id", event.get("ref"))
        repeats = event.get("repeats", 1)
        if (line_id not in evidence or type(repeats) is not int or repeats < 1):
            raise ValueError("translation context has unknown reference or invalid repeats")
        for repeat in range(repeats):
            counts[line_id] = counts.get(line_id, 0) + 1
            occurrences.append({"line_id": line_id, "occurrence": counts[line_id], "repeat_index": repeat})
    seeds = set(target_ids) | explicit_refs
    relations = []
    # Follow only actual target/referenced relations, not every incidental neighbor.
    pending = list(seeds)
    visited = set()
    while pending:
        line_id = pending.pop(0)
        if line_id in visited:
            continue
        visited.add(line_id)
        row = evidence.get(line_id)
        if not row or not isinstance(row.get("gloss"), dict):
            raise ValueError("translation context lacks referenced gloss: " + line_id)
        relation = row["gloss"].get("semantic_frame", {}).get("cross_line_relation", "")
        if relation:
            relations.append({"line_id": line_id, "cross_line_relation": relation})
            for known_id in evidence:
                if re.search(r"(?<![\w-])" + re.escape(known_id) + r"(?![\w-])", str(relation)):
                    if known_id not in seeds:
                        seeds.add(known_id)
                        pending.append(known_id)
    intervals = []
    seen_seeds = set()
    for index, event in enumerate(occurrences):
        if event["line_id"] in seeds:
            seen_seeds.add(event["line_id"])
            start, end = max(0, index - 3), min(len(occurrences), index + 4)
            if intervals and start <= intervals[-1][1]:
                intervals[-1][1] = max(intervals[-1][1], end)
            else:
                intervals.append([start, end])
    if seeds - seen_seeds:
        raise ValueError("translation context target/reference absent from order")
    selected = []
    windows = []
    for start, end in intervals:
        window = occurrences[start:end]
        windows.append({"occurrences": window,
                        "target_ids": [i for i in target_ids if any(o["line_id"] == i for o in window)]})
        for occurrence in window:
            if occurrence["line_id"] not in selected:
                selected.append(occurrence["line_id"])
    context_ids = [i for i in selected if i not in target_ids]
    if len(context_ids) > 80:
        raise ValueError("translation context exceeds 80-row scope limit")
    for line_id in selected:
        row = evidence[line_id]
        if any(not isinstance(row.get(key), dict) or row[key].get("id") != line_id
               for key in ("source", "gloss", "draft")):
            raise ValueError("translation context lacks source/gloss/draft: " + line_id)
        if not isinstance(row["draft"].get("literal_english"), str):
            raise ValueError("translation context lacks English: " + line_id)
    return {"version": 1, "order_basis": order_basis, "targets": list(target_ids),
            "context_rows": [evidence[i] for i in context_ids],
            "reading_windows": windows, "relation_notes": sorted(relations, key=lambda row: row["line_id"]), "scope_issues": []}


def translation_review_payload(target_evidence: list[dict[str, Any]], reading_context: dict[str, Any]) -> dict[str, Any]:
    """One source definition per supplied row; actual windows own adjacency.

    Lexical retrieval still receives the original rich source internally. Only
    redundant nested neighbor copies are removed from the review payload.
    """
    targets = copy.deepcopy(target_evidence)
    reading = copy.deepcopy(reading_context)
    if not isinstance(reading, dict) or not isinstance(reading.get("context_rows"), list):
        raise ValueError("review payload requires bounded reading context")
    expected = reading.get("targets")
    if not isinstance(targets, list) or not targets or not isinstance(expected, list):
        raise ValueError("review payload requires exact target evidence")
    supplied = set()
    target_ids = []
    for index, row in enumerate(targets + reading["context_rows"]):
        if not isinstance(row, dict) or not isinstance(row.get("source"), dict):
            raise ValueError("review payload row lacks source")
        line_id = row["source"].get("id")
        if not isinstance(line_id, str) or not line_id or line_id in supplied:
            raise ValueError("review payload has missing or duplicate source definition")
        supplied.add(line_id)
        if index < len(targets): target_ids.append(line_id)
        row["source"].pop("performed_context", None)
    if target_ids != expected:
        raise ValueError("review payload target IDs differ from reading obligations")
    windows = reading.get("reading_windows")
    if not isinstance(windows, list) or not windows:
        raise ValueError("review payload lacks performed reading windows")
    referenced = set()
    for window in windows:
        if not isinstance(window, dict) or not isinstance(window.get("occurrences"), list):
            raise ValueError("review payload has invalid reading window")
        for occurrence in window["occurrences"]:
            if not isinstance(occurrence, dict) or occurrence.get("line_id") not in supplied:
                raise ValueError("review payload window refers to an absent source definition")
            referenced.add(occurrence["line_id"])
    if referenced != supplied:
        raise ValueError("review payload has unbound source definitions")
    return {"target_evidence": targets, "reading_context": reading}


def independently_review_translations(
    song_dir: Path, lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]],
    translation_rows: list[dict[str, Any]], provided_translation: str, options: argparse.Namespace,
    languages: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gloss_by_id = {row["id"]: row for row in gloss_rows}
    translation_by_id = {row["id"]: row for row in translation_rows}
    support = bhakti_lexical_support.prepare_options(options, lines, languages)
    policy = semantic_stage_policy(options)
    policy = {**policy, 'review_payload_contract': 1, 'pending_findings': getattr(options, 'semantic_pending_findings', []),
              'repair_findings': getattr(options, 'semantic_repair_findings', [])}
    review_schema = translation_review_schema()
    if getattr(options, 'semantic_repair_findings', []):
        row_schema = review_schema['properties']['reviews']['items']
        row_schema['properties']['finding_dispositions'] = {
            'type': 'array', 'items': {'type': 'object', 'properties': {
                'finding_id': {'type': 'string'},
                'status': {'type': 'string', 'enum': ['repaired', 'unresolved']},
                'source_quote': {'type': 'string'}, 'explanation': {'type': 'string'}},
                'required': ['finding_id', 'status', 'source_quote', 'explanation'],
                'additionalProperties': False}}
        row_schema['required'].append('finding_dispositions')
    # Review outputs are verbose enough that 40-line packets can hit a model or
    # gateway output ceiling on long works. Twenty-line parent caches, issued as
    # ten-line requests below, keep evidence complete without a failed response.
    batches = [lines[index:index + 20] for index in range(0, len(lines), 20)]
    # Preflight every eventual request before workers can spend on an earlier one.
    full_evidence = list(getattr(options, "semantic_context_evidence", []))
    full_evidence.extend({**row, "explicit_reference": True}
                         for row in getattr(options, "semantic_distant_context", []))
    reading_contexts = {}
    for batch in batches:
        for offset in range(0, len(batch), 10):
            ids = tuple(line["id"] for line in batch[offset:offset + 10])
            reading_contexts[ids] = translation_reading_context(
                lines, gloss_rows, translation_rows, list(ids),
                performance_order=getattr(options, "semantic_performance_order", []),
                full_evidence=full_evidence)
    review_payloads = {}
    source_by_id = {line["id"]: line for line in lines}
    for ids, reading in reading_contexts.items():
        evidence = [{"source": source_by_id[line_id], "gloss": gloss_by_id[line_id],
                     "draft": translation_by_id[line_id]} for line_id in ids]
        review_payloads[ids] = translation_review_payload(evidence, reading)
    cache_dir = song_dir / ".transcription" / "pipeline" / "translation-review-batches"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def select_response(response, target_ids, source_context, label):
        context_ids = list(target_ids)
        for ids, reading in reading_contexts.items():
            if set(target_ids).intersection(ids):
                context_ids.extend(row["source"]["id"] for row in reading["context_rows"])
        context_ids = list(dict.fromkeys(context_ids))
        observer = getattr(options, 'semantic_review_observer', None)
        if observer is not None:
            observer(copy.deepcopy(response), list(target_ids), str(label), context_ids)
        reviews = stage_model_rows(response, 'reviews', options)
        try:
            selected = select_translation_review_rows(reviews, target_ids, context_ids)
        except ValueError as exc:
            stage_quality_failure(options, f"translation review batch {label}: {exc}")
        if observer is None:
            # Journal-aware audits retain these separately. Other callers must
            # hold rather than silently discard material or malformed context.
            fidelity = ("passes", "agency_preserved", "imagery_preserved",
                        "all_meaning_accounted_for")
            unresolved = [row["id"] for row in reviews if row["id"] not in target_ids
                and (any(row.get(flag) is not True for flag in fidelity)
                     or row.get("human_review_recommended") is not False
                     or row.get("issues") != [] or row.get("unsupported_additions") != []
                     or any(not isinstance(row.get(key), str) for key in ("reason", "material_choice")))]
            if unresolved:
                stage_quality_failure(options,
                    f"translation review has unresolved or malformed context dependencies: {unresolved}",
                    kind="unresolved_context")
        # Keep the provider response and its flags intact in candidate-*.json.
        result = copy.deepcopy(response)
        result["packet"]["reviews"] = copy.deepcopy(selected)
        observed = [row["id"] for row in reviews]
        if "review_selection" not in result or observed != target_ids:
            result["review_selection"] = {
                "version": 1, "observed_ids": observed, "target_ids": list(target_ids),
                "excluded_context_ids": [line_id for line_id in observed if line_id not in target_ids],
            }
        return result

    def run(index: int) -> dict[str, Any]:
        batch = batches[index]
        context = nearby_text_context(lines, index * 20, len(batch))
        expected = [line["id"] for line in batch]
        evidence = [{"source": line, "gloss": gloss_by_id[line["id"]],
                     "draft": translation_by_id[line["id"]]} for line in batch]
        fingerprint = text_stage_fingerprint("translation-review", options.model,
            {"evidence": evidence, "context": context, "provided_translation": provided_translation,
             "languages": languages, "reading_context": [reading_contexts[tuple(expected[offset:offset + 10])]
                 for offset in range(0, len(expected), 10)]}, policy)
        path = cache_dir / f"batch-{index:03d}.json"
        cached = read_packet(path)
        if cached and cached.get("fingerprint") == fingerprint and not options.force:
            result = copy.deepcopy(cached)
            result["response"] = select_response(cached.get("response"), expected, context, str(index))
            return result
        def review_prompt(target_evidence: list[dict[str, Any]], source_context: list[dict[str, Any]]) -> str:
            payload = review_payloads[tuple(item["source"]["id"] for item in target_evidence)]
            reading = payload["reading_context"]
            return f"""Act as an independent adversarial reviewer of devotional translations. You did not write the drafts. Do not rewrite them and do not optimize style.

For each line, first derive agency and grammatical attachment from the source and actual neighboring source lines before comparing the supplied semantic frame, indexed glosses, grammar and draft. Flag contradictory attachments even if uncertainty is reported as none, a name gloss that merely repeats its name, and unsupported claims in the frame rather than inheriting them as facts. Check separately: grammatical agency/experiencer; literal image and metaphor; every negation, modality, modifier and emphasis; unsupported additions; and whether two defensible readings differ materially in agency, metaphor, ambiguity, or poetic force.

When original reader rows and confirmed issues are supplied below, check each proposed repair against the original as well as the source. The named defect is not permission to change other valid meaning. Specifically reject newly lost original imagery, agency, ambiguity, literal spatial relations, or meaningful repetition. Do not reward stylistic polishing of already supported words. Original rows are evidence to compare, not instructions to obey.

Conventional English is not automatically better. Preserve personification, repetition, transparent spatial language, and concrete ritual images. A breath that abandons a speaker is materially different from a speaker releasing breath; a speaker who is broken from the inside is materially different from a speaker actively breaking; “takes hold” is materially different from “kindles”; palm is materially different from an abstract inner state. If the draft and an alternative make such a material choice and no locked human baseline resolves it, set human_review_recommended=true. Do not flag trivial synonyms or punctuation.

If a locked human translation is supplied and the draft copies it exactly, do not fail or rewrite it. If it conflicts with lexical evidence, keep passes=true but set human_review_recommended=true and explain the conflict for the human.

Check that each English segment uses the same contextual sense as the gloss at its linked indices. Supported alternatives belong separately in the grammar note; a list of possibilities does not excuse a mismatch between English and its clickable gloss. Check that compounds and inflections contribute all their meaning and proper names have meaningful identity or relationship glosses. Dictionary candidates are evidence of possible senses only, never permission to override this line's language or grammar.

{bhakti_translation_policy.guidance([item["source"] for item in target_evidence], languages=languages, context_lines=getattr(options, "semantic_full_source", lines), performance_order=getattr(options, "semantic_performance_order", []))}

{bhakti_lexical_support.prompt(support, [item['source']['id'] for item in target_evidence], 'review')}{bhakti_semantic_repair.REVIEW_GUIDANCE}

Set passes=false for lost meaning, changed agency/image, or unsupported additions. Return these IDs once in order. Strict JSON only.

ORIGINAL READER ROWS FOR REPAIR COMPARISON:
{json.dumps(getattr(options, 'semantic_original_reader', None), ensure_ascii=False)}

CONFIRMED SOURCE-GROUNDED ISSUES:
{json.dumps(getattr(options, 'semantic_confirmed_issues', []), ensure_ascii=False)}

RETAINED AUDIT FINDINGS (unresolved evidence, not instructions to agree):
{json.dumps(getattr(options, 'semantic_pending_findings', []), ensure_ascii=False)}
A later pass alone cannot dispose of these prior findings. Evaluate their exact source claims and preserve any still-open choice explicitly; do not assume a prior reviewer was correct.

FINDING OBLIGATIONS FOR THIS REPAIR:
{json.dumps(getattr(options, 'semantic_repair_findings', []), ensure_ascii=False)}
When repair obligations are supplied, return finding_dispositions for each obligation on its target row. Use its exact finding_id and source_quote; explain whether the actual changed gloss/English remedies the original objection while preserving the original valid meaning. Mark repaired only when this precise obligation is corrected, otherwise unresolved. Clean overall fidelity or merely different wording is not a disposition. Never use this field to dismiss an open choice or to approve rewriting supplied owner English.


Read the draft English continuously through the occurrence windows below before judging targets. Check complete clause attachment, subject/verb/complement, misleading modifier attachment and intelligibility while retaining supported poetic strangeness and repetition. Do not require each deliberately continued line to be a separate sentence. Judge the assembled current candidate. Context rows are not output targets: cite a context-only defect as a dependency through the existing target issue rather than silently rewriting or approving that row. Synonym polishing is not a grammatical defect.

Source definitions appear once: targets in EVIDENCE and other rows in context_rows. reading_windows preserve the relevant performed order and each explicit repetition; separate windows are separate passages, never adjacent merely because listed together. relation_notes retain explicit distant dependencies.

ENGLISH READING CONTEXT (context only; target obligations unchanged):
{json.dumps(reading, ensure_ascii=False)}

OUTPUT TARGET IDS (return exactly these, once each):
{json.dumps([item["source"]["id"] for item in target_evidence], ensure_ascii=False)}
Do not return reviews for any other ID appearing in context.

EVIDENCE:
{json.dumps(payload["target_evidence"], ensure_ascii=False)}

LOCKED HUMAN TRANSLATION (or none):
{provided_translation}"""

        def request(target_evidence: list[dict[str, Any]], target_ids: list[str], label: str,
                    source_context: list[dict[str, Any]]) -> dict[str, Any]:
            response = gemini.call(options.model, gemini.key(), review_prompt(target_evidence, source_context), audio=None,
                                   timeout=stage_call_timeout(options),
                                       response_schema=review_schema,
                                   schema_name="bhakti_translation_review", reasoning_effort="high",
                                   max_completion_tokens=32768, **stage_transport_context(options))
            write_json(cache_dir / f"candidate-{label.replace('.', '-')}.json", response)
            return select_response(response, target_ids, source_context, label)

        if len(batch) > 10:
            children = []
            for child_index, offset in enumerate(range(0, len(batch), 10)):
                child_evidence = evidence[offset:offset + 10]
                child_ids = expected[offset:offset + 10]
                child_context = nearby_text_context(lines, index * 20 + offset, len(child_evidence))
                child_fingerprint = text_stage_fingerprint("translation-review", options.model,
                    {"evidence": child_evidence, "context": child_context, "provided_translation": provided_translation,
                     "languages": languages, "reading_context": reading_contexts[tuple(child_ids)]}, policy)
                child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                child_packet = read_packet(child_path)
                if not (child_packet and child_packet.get("fingerprint") == child_fingerprint
                        and not options.force):
                    child_packet = {
                        "fingerprint": child_fingerprint,
                        "target_ids": child_ids,
                        "response": request(child_evidence, child_ids, f"{index}.{child_index}", child_context),
                    }
                    write_json(child_path, child_packet)
                child_packet = copy.deepcopy(child_packet)
                child_packet["response"] = select_response(
                    child_packet.get("response"), child_ids, child_context, f"{index}.{child_index}")
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
                      "response": request(evidence, expected, str(index), context)}
        write_json(path, result)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(batches))) as pool:
        packets = list(pool.map(run, range(len(batches))))
    reviews = [row for packet in packets for row in packet["response"]["packet"]["reviews"]]
    return reviews, packets


def translate(song_dir: Path, audited: dict[str, Any], glosses: dict[str, Any], job: dict[str, Any], options: argparse.Namespace, *, candidate_only: bool = False) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "05-translation.json"
    lines = audited['packet'].get('verified_lines', [])
    gloss_rows = glosses['packet'].get('glosses', [])
    gloss_by_id = {row['id']: row for row in gloss_rows}
    provided_translation = supplied_translation(job)
    audited_languages = audited.get("packet", {}).get("metadata", {}).get("languages")
    languages = job.get("languages", audited_languages)
    def language_identity(value: Any) -> set[str]:
        aliases = {"hi": "hindi", "hindustani": "hindi", "classical hindi": "hindi"}
        return {aliases.get(str(item).strip().casefold(), str(item).strip().casefold())
                for item in (value or [])}
    for label, evidence_languages in (("audited source", audited_languages),
                                      ("gloss evidence", glosses.get("sense_languages"))):
        if evidence_languages is not None and language_identity(evidence_languages) != language_identity(languages):
            raise RuntimeError(f"translation language conflicts with {label}")
    sense_errors = bhakti_translation_policy.sense_decision_errors(lines, gloss_rows, languages)
    if sense_errors:
        raise RuntimeError(f"translation input violates sense evidence contract: {sense_errors[:3]}")
    support = bhakti_lexical_support.prepare_options(options, lines, languages)
    support_errors = bhakti_lexical_support.support_decision_errors(support, gloss_rows)
    if support_errors:
        raise RuntimeError("translation lexical support: " + str(support_errors[:3]))
    policy = semantic_stage_policy(options)
    fingerprint = text_stage_fingerprint("translation", options.model,
        translation_stage_inputs(lines, gloss_rows, provided_translation, languages, options,
            performance_order=audited["packet"].get("performance_order", [])), policy)
    existing = read_packet(target)
    if (existing and existing.get("fingerprint") == fingerprint and not options.force
            and existing.get("input_contract_version") == TRANSLATION_INPUT_VERSION):
        errors = fresh_translation_contract_errors(
            lines, gloss_rows, existing.get("packet", {}).get("translations", []))
        errors.extend(bhakti_lexical_support.support_decision_errors(support, gloss_rows, existing.get("packet", {}).get("translations", [])))
        if errors:
            raise RuntimeError(f"cached translation violates fresh contract: {errors[:3]}")
        return existing
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
6. Translate ordinary words and philosophical concepts into precise English, using a short contextual phrase even for registry-listed concepts. A `concept_key` is bookkeeping, not an instruction to leave the term untranslated. Retain a concept in IAST only when explicitly supplied locked English does so; a legacy `preserve_in_english=true` flag alone cannot override this rule. Retain genuine proper names, whose clickable gloss must explain their evidenced identity or relationship. The sense used in every English segment must match the chosen primary meaning at its linked word indices, including compounds and inflections; supported alternatives remain separately explained in grammar notes.

{bhakti_translation_policy.guidance(batch, languages=languages, context_lines=getattr(options, "semantic_full_source", lines), performance_order=getattr(options, "semantic_performance_order", audited["packet"].get("performance_order", [])))}{bhakti_lexical_support.prompt(support, [line['id'] for line in batch], 'translation')}

For each line, return plain literal English plus ordered display segments. Read adjacent lines as a continuous utterance before deciding syntax, punctuation, ellipsis, pronouns, or repeated words; a line may be a deliberate grammatical continuation. Each segment may reference the exact word indices which support it; punctuation or necessary English function-word segments can use an empty index list. Every source word index must appear in at least one segment. Map particles, postpositions, tense/aspect, negation, modality, and honorifics to the English phrase they help create rather than leaving their source index uncovered.

Write lucid devotional English, but do not confuse conventional English with better poetry. Literal strangeness, repetition, personification, unusual agency, and concrete bodily or ritual imagery may be the point. Preserve a supported image such as “my breath will abandon me” even if an English idiom such as “I will breathe my last” sounds smoother. Preserve suffered/resultant states as states: if the lyric says the speaker is broken, keep that brokenness rather than recasting it as the speaker actively broke. Never replace the source's agency, metaphor, ambiguity, or emotional logic merely to sound idiomatic. Correct wording only when it is demonstrably wrong, ungrammatical, or obstructs understanding. Avoid legalistic filler, accidental inversion, duplicate modifiers, and unsupported editorial verbs. Retain sacred sight or encounter as the context warrants, an alms bag, garment hem, cupped or open palm, lotus, dust, ocean, threshold, cage, and Mount Meru when the source supports them.

Use established English words. A rare but attested word is acceptable when it is precise and remains understandable in context. A transparent, source-supported compound may join two ordinary words, preferably with a hyphen when that aids reading. Never invent pseudo-Latin vocabulary or use a franchise-specific fictional coinage such as `adamantium`, `vibranium`, or `mithril`. `Adamantine` is an established English adjective and is not the fictional noun `adamantium`.

Resolve ordinary polysemy from the supplied grammar/song context. When two defensible renderings differ materially in agency, metaphor, ambiguity, or poetic force, include both in `material_alternatives` and set `human_review_recommended=true` instead of silently optimizing for smoothness. This is not required for trivial synonyms. The completed segments must reconstruct `literal_english` exactly, including ordinary spacing and punctuation. Then report a fidelity check: whether agency/image and all source meaning were preserved, every unsupported addition (normally none), and a concise note naming any nonliteral idiom or necessary English function word.

Do not flatten jāti, jñātī, jāta-pāta, and varṇa into an undifferentiated “caste.” Translate jāti/jñātī contextually as community, clan, kin group, or occupational group; translate varṇa as the broader fourfold social order or its rank/classification. When a source contrasts jāti and varṇa, make that distinction intelligible in English.

{semantic_repair_prompt(options)}

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
    # Literal translations carry indexed English segments, alternatives, and
    # fidelity evidence.  Keep medium recordings in the same bounded batch
    # path as long recordings rather than waiting on one oversized response.
    selected = getattr(options, 'semantic_translation_targets', None)
    candidate_lines = [line for line in lines if line['id'] in selected] if selected is not None else lines
    if not candidate_lines:
        raise RuntimeError('semantic repair has no translation targets')
    cached_candidate = read_packet(target.parent / 'translation-candidate.json') if candidate_only else None
    reuse_candidate = bool(cached_candidate and cached_candidate.get('fingerprint') == fingerprint
                           and cached_candidate.get('input_contract_version') == TRANSLATION_INPUT_VERSION)
    if reuse_candidate:
        result = copy.deepcopy(cached_candidate)
    elif candidate_only and getattr(options, 'semantic_seed_translation', None):
        result = copy.deepcopy(options.semantic_seed_translation)
    elif len(candidate_lines) <= 40:
        result = gemini.call(options.model, gemini.key(), prompt_for(candidate_lines, []), audio=None, timeout=stage_call_timeout(options),
                                       response_schema=bhakti_lexical_support.extend_schema(schema, support, "translation"), schema_name="bhakti_literal_translation",
                             reasoning_effort="high", max_completion_tokens=65536, **stage_transport_context(options))
    else:
        # Preserve the historical 40-line parent cache shape so already
        # completed work remains reusable, but issue fresh requests in bounded
        # 20-line children. Long translation JSON contains indexed segments and
        # fidelity evidence; a 40-line response can be truncated even with the
        # provider ceiling set to 65,536 tokens.
        batches = [candidate_lines[index:index + 40] for index in range(0, len(candidate_lines), 40)]
        cache_dir = song_dir / ".transcription" / "pipeline" / "translation-batches"
        cache_dir.mkdir(parents=True, exist_ok=True)

        def run(index: int) -> dict[str, Any]:
            batch = batches[index]
            expected = [line["id"] for line in batch]
            cache_path = cache_dir / f"batch-{index:03d}.json"
            start = index * 40
            def batch_fingerprint(target_lines: list[dict[str, Any]], absolute_start: int) -> str:
                return text_stage_fingerprint("translation-batch", options.model,
                    {"lines": target_lines,
                     "glosses": [gloss_by_id[line["id"]] for line in target_lines],
                     "context": nearby_text_context(lines, absolute_start, len(target_lines)),
                     "provided_translation": provided_translation, "languages": languages}, policy)
            batch_identity = batch_fingerprint(batch, start)
            cached = read_packet(cache_path)
            if (cached and cached.get("target_ids") == expected
                    and cached.get("fingerprint") == batch_identity
                    and cached.get("input_contract_version") == TRANSLATION_INPUT_VERSION and not options.force):
                return cached

            def request(target_lines: list[dict[str, Any]], absolute_start: int, label: str) -> dict[str, Any]:
                target_ids = [line["id"] for line in target_lines]
                context = nearby_text_context(lines, absolute_start, len(target_lines))
                response = gemini.call(options.model, gemini.key(), prompt_for(target_lines, context), audio=None,
                                       timeout=stage_call_timeout(options),
                                       response_schema=bhakti_lexical_support.extend_schema(schema, support, "translation"),
                                       schema_name="bhakti_translation_batch", reasoning_effort="high",
                                       max_completion_tokens=65536, **stage_transport_context(options))
                returned = [row.get("id") for row in response["packet"].get("translations", [])]
                compared = [row.get("id") for row in response["packet"].get("comparison", [])]
                if returned != target_ids or compared != target_ids:
                    stage_quality_failure(options, f"translation batch {label} returned IDs out of order or incomplete")
                return response

            if len(batch) > 20:
                children = []
                for child_index, offset in enumerate(range(0, len(batch), 20)):
                    child = batch[offset:offset + 20]
                    child_ids = [line["id"] for line in child]
                    child_path = cache_dir / f"batch-{index:03d}-{child_index:02d}.json"
                    child_packet = read_packet(child_path)
                    child_identity = batch_fingerprint(child, start + offset)
                    if not (child_packet and child_packet.get("target_ids") == child_ids
                            and child_packet.get("fingerprint") == child_identity
                            and child_packet.get("input_contract_version") == TRANSLATION_INPUT_VERSION
                            and not options.force):
                        child_packet = {
                            "target_ids": child_ids,
                            "input_contract_version": TRANSLATION_INPUT_VERSION,
                            "fingerprint": child_identity,
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
                          "fingerprint": batch_identity, "response": response, "child_batches": children}
            else:
                packet = {"target_ids": expected, "input_contract_version": TRANSLATION_INPUT_VERSION,
                          "fingerprint": batch_identity, "response": request(batch, start, str(index))}
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
    if selected is not None and not reuse_candidate:
        returned = result['packet']['translations']
        if [row.get('id') for row in returned] != [row['id'] for row in candidate_lines]:
            stage_quality_failure(options, 'semantic repair translation target population changed')
        replacements = {row['id']: row for row in returned}
        old = {row['id']: row for row in getattr(options, 'semantic_previous_translations', [])}
        if set(old) != {line['id'] for line in lines}:
            raise RuntimeError('semantic repair previous translation population changed')
        result['packet']['translations'] = [copy.deepcopy(replacements.get(line['id'], old[line['id']])) for line in lines]
    support_errors = bhakti_lexical_support.support_decision_errors(support, gloss_rows, result['packet']['translations'])
    if support_errors:
        raise RuntimeError('translation lexical support: ' + str(support_errors[:3]))
    for row in result['packet']['translations']:
        row.pop('independent_review', None)
    result["input_contract_version"] = TRANSLATION_INPUT_VERSION
    result["fingerprint"] = fingerprint
    candidate_path = target.parent / 'translation-candidate.json'
    semantic_write_json(candidate_path, result)
    bhakti_semantic_repair.assert_baseline(getattr(options, 'semantic_baseline', None), result['packet']['translations'])
    review_options = copy.copy(options)
    review_options.semantic_performance_order = copy.deepcopy(
        getattr(options, "semantic_performance_order", audited["packet"].get("performance_order", [])))
    if hasattr(options, 'semantic_deadline_at'):
        # All final review batches bind the complete assembled evidence. Their
        # payload stays bounded: full source, targets, explicit distant refs.
        review_options.semantic_review_snapshot = bhakti_semantic_repair.digest({
            'lines': lines, 'glosses': gloss_rows, 'translations': result['packet']['translations']})
        references = {ref['line_id'] for issue in getattr(options, 'semantic_repair_feedback', [])
                      for ref in issue.get('references', [])}
        review_options.semantic_distant_context = [
            {'source': line, 'gloss': gloss_by_id[line['id']],
             'draft': next(row for row in result['packet']['translations'] if row['id'] == line['id'])}
            for line in lines if line['id'] in references]
    independent_reviews, review_packets = independently_review_translations(
        song_dir, lines, gloss_rows, result["packet"]["translations"], provided_translation, review_options,
        languages=languages
    )
    review_by_id = {row["id"]: row for row in independent_reviews}
    for row in result["packet"]["translations"]:
        row["independent_review"] = review_by_id.get(row["id"], {})
    result["review_responses"] = review_packets
    semantic_write_json(candidate_path, result)
    errors = fresh_translation_contract_errors(lines, gloss_rows, result["packet"]["translations"])
    if candidate_only:
        return result
    if errors:
        stage_quality_failure(options, f"translation output violates fresh contract: {errors[:3]}")
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
        if str(line.get("kind") or "") == "instrumental":
            continue
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


def fresh_translation_contract_errors(
    lines: list[dict[str, Any]], gloss_rows: list[dict[str, Any]],
    translation_rows: list[dict[str, Any]],
) -> list[str]:
    """Require affirmative semantic review before accepting a new 05 packet.

    Historical generate-only packets retain their existing validation path.
    Model assertions are necessary evidence here, not proof of linguistic truth.
    """
    errors = validate_ids(lines, gloss_rows, translation_rows)
    expected_ids = [line.get("id") for line in lines]
    if [row.get("id") for row in translation_rows] != expected_ids:
        errors.append("fresh translation IDs must occur exactly once in source order")
    instrumental = {line.get("id") for line in lines if line.get("kind") == "instrumental"}
    for row in translation_rows:
        line_id = row.get("id", "<unknown>")
        if line_id in instrumental:
            continue
        for field, required in (
            ("fidelity", ("agency_and_image_preserved", "all_meaning_accounted_for")),
            ("independent_review", ("passes", "agency_preserved", "imagery_preserved", "all_meaning_accounted_for")),
        ):
            evidence = row.get(field)
            if not isinstance(evidence, dict) or not evidence:
                errors.append(f"{line_id} lacks a nonempty {field} record")
                continue
            for key in required:
                if evidence.get(key) is not True:
                    errors.append(f"{line_id} {field}.{key} must be true")
            if evidence.get("unsupported_additions") != []:
                errors.append(f"{line_id} {field}.unsupported_additions must be an empty list")
        if row.get("human_review_recommended") is not False:
            errors.append(f"{line_id} translation lacks an explicit resolved review status")
        independent = row.get("independent_review")
        if isinstance(independent, dict) and independent.get("human_review_recommended") is not False:
            errors.append(f"{line_id} independent_review lacks an explicit resolved review status")
        parts = row.get("segments")
        if (not isinstance(parts, list) or not parts
                or any(not isinstance(part, dict) or not isinstance(part.get("text"), str)
                       or not isinstance(part.get("word_indices"), list) for part in parts)):
            errors.append(f"{line_id} lacks valid English segments")
        else:
            # Render through the same spacing/punctuation normalizer as the
            # public indexed English, omitting only the index markup.
            displayed = segment_english([{**part, "word_indices": []} for part in parts], "")
            if displayed != row.get("literal_english"):
                errors.append(f"{line_id} English segments do not reconstruct literal_english")
    for row in gloss_rows + translation_rows:
        if str(row.get("uncertainty") or "").strip().casefold() not in {"", "none", "no", "null", "n/a"}:
            errors.append(f"{row.get('id')} has unresolved gloss or translation uncertainty")
    # The legacy validator assumes structurally valid rows; malformed fresh
    # evidence must fail as a useful contract error rather than an exception.
    if errors:
        return errors
    return validate_line_contract(lines, gloss_rows, translation_rows)


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


VERSE_MARKER_SOURCE = re.compile(r"(?:॥|\|\|)\s*[०-९0-9]+(?:\([कख]\))?\s*(?:॥|\|\|)\s*$")
VERSE_MARKER_ROMAN = re.compile(r"\s*(?:(?:\.\.)|॥|\|\|)?\s*[0-9]+(?:\((?:ka|kha)\))?\s*(?:(?:\.\.)|॥|\|\||\.)?\s*$")
VERSE_MARKER_ENGLISH = re.compile(r"\s*(?:[.॥|]*\s*)?[0-9]+[ab]?(?:\s*[.॥|]+)?\s*$")
DOHA_PREFIX_SOURCE = re.compile(r"^\s*दो(?:हा)?(?:[.०0=]+)?\s*[-=]?\s*")
CHHAND_PREFIX_SOURCE = re.compile(r"^\s*छं(?:[.=]+)?\s*")
SORATHA_PREFIX_SOURCE = re.compile(r"^\s*सो(?:[.=]+)\s*")
DOHA_PREFIX_ROMAN = re.compile(r"^\s*d[ōo](?:[.0=]+)?\s*")
CHHAND_PREFIX_ROMAN = re.compile(r"^\s*chaṃ(?:[.=]+)?\s*")
SORATHA_PREFIX_ROMAN = re.compile(r"^\s*s[ōo](?:[.=]+)\s*")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def has_terminal_verse_marker(source: str) -> bool:
    """A metrical number is bibliographic structure, not sung/translatable text."""
    return bool(VERSE_MARKER_SOURCE.search(str(source or "")))


def display_roman_without_verse_marker(roman: str, source: str) -> str:
    return VERSE_MARKER_ROMAN.sub("", roman).rstrip() if has_terminal_verse_marker(source) else roman


def display_source_without_verse_marker(source: str) -> str:
    return VERSE_MARKER_SOURCE.sub("", str(source or "")).rstrip()


def is_verse_marker_english_segment(text: object) -> bool:
    return bool(VERSE_MARKER_ENGLISH.fullmatch(str(text or "")))


def strip_terminal_verse_marker_english(text: object) -> str:
    return VERSE_MARKER_ENGLISH.sub("", str(text or "")).rstrip()


def metrical_prefix(source: str) -> tuple[str, str, re.Pattern[str] | None]:
    """Return a display note and source without a printed meter abbreviation."""
    for title, pattern in (("Dohā", DOHA_PREFIX_SOURCE), ("Chhand", CHHAND_PREFIX_SOURCE),
                           ("Sorathā", SORATHA_PREFIX_SOURCE)):
        if pattern.match(source):
            return title, pattern.sub("", source, count=1), pattern
    return "", source, None


def nearby_dohā_number(lines: list[dict[str, Any]], line_index: int) -> str:
    """Dohā labels name the couplet whose printed number follows within two lines."""
    for candidate in lines[line_index:line_index + 3]:
        match = re.search(r"[॥|]\s*([०-९0-9]+)\s*[॥|]\s*$", str(candidate.get("source_text", "")))
        if match:
            return match.group(1).translate(DEVANAGARI_DIGITS)
    return ""


def language_code(language: str) -> str:
    return {"Hindi": "hi", "Sanskrit": "sa", "Punjabi": "pa", "Kannada": "kn", "Marathi": "mr",
            "Awadhi": "awa", "Braj": "bra", "Rajasthani": "raj", "Tamil": "ta", "Telugu": "te",
            "Odia": "or", "Bengali": "bn", "Malayalam": "ml", "Persian": "fa", "Urdu": "ur"}.get(language, "")


def resolve_reviewed_languages(
    slug: str, audited_lines: list[dict[str, Any]], performance_order: list[dict[str, Any]],
    supplied_song_languages: list[str], *, root: Path,
) -> dict[str, Any]:
    """Resolve exact audited-source language evidence without guessing from script.

    The registry pins unique performed source_text strings, before display cleanup.
    Unperformed definitions retain annotations but cannot supply performed evidence.
    This function validates everything before returning; it never mutates inputs.
    """
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate language registry key: {key}")
            result[key] = value
        return result

    def known_language(value: Any) -> tuple[str, str]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("reviewed language must be a nonempty language name or code")
        name = normalized_language(value)
        code = language_code(name)
        if not code:
            raise ValueError(f"unrecognized reviewed language: {value!r}")
        return name, code

    path = Path(root) / "data" / "song_language_overrides.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except FileNotFoundError:
        registry = {"version": 1, "songs": {}}
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid language registry: {exc}") from exc
    if (not isinstance(registry, dict) or type(registry.get("version")) is not int
            or registry["version"] != 1 or not isinstance(registry.get("songs"), dict)):
        raise ValueError("invalid language registry structure")
    records = {}
    for registered_slug, record in registry["songs"].items():
        if (not isinstance(registered_slug, str) or not registered_slug.strip()
                or not isinstance(record, dict) or not isinstance(record.get("languages"), list)
                or not record["languages"] or not isinstance(record.get("lines"), list)
                or not isinstance(record.get("performedSourcesSha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", record["performedSourcesSha256"])):
            raise ValueError(f"invalid language registry record: {registered_slug!r}")
        languages = [known_language(value)[0] for value in record["languages"]]
        if len(set(languages)) != len(languages):
            raise ValueError(f"{registered_slug}: duplicate reviewed song languages")
        assignments = {}
        for item in record["lines"]:
            if (not isinstance(item, dict) or not isinstance(item.get("source"), str)
                    or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
                raise ValueError(f"{registered_slug}: invalid language source evidence")
            name, code = known_language(item.get("language"))
            if name not in languages:
                raise ValueError(f"{registered_slug}: line language is outside reviewed song languages")
            if item["source"] in assignments and assignments[item["source"]] != code:
                raise ValueError(f"{registered_slug}: conflicting source language assignments")
            assignments[item["source"]] = code
        records[registered_slug] = (languages, assignments, record["performedSourcesSha256"])
    if not isinstance(audited_lines, list) or not isinstance(performance_order, list):
        raise ValueError("invalid audited lines or language performance order")
    lines_by_id = {}
    for line in audited_lines:
        if (not isinstance(line, dict) or not isinstance(line.get("id"), str) or not line["id"]
                or line["id"] in lines_by_id or not isinstance(line.get("source_text"), str)):
            raise ValueError("invalid or duplicate audited language source line")
        lines_by_id[line["id"]] = line
    performed_sources = set()
    for event in performance_order:
        ref = event.get("ref", event.get("line_id")) if isinstance(event, dict) else None
        if not isinstance(ref, str) or ref not in lines_by_id:
            raise ValueError(f"invalid language performance reference: {ref!r}")
        performed_sources.add(lines_by_id[ref]["source_text"])
    assignments = {}
    if slug in records:
        languages, assignments, expected_digest = records[slug]
        coverage = json.dumps(sorted(performed_sources), ensure_ascii=False, separators=(",", ":"))
        if hashlib.sha256(coverage.encode("utf-8")).hexdigest() != expected_digest:
            raise ValueError(f"{slug}: performed language source coverage changed; review required")
        if performed_sources.difference(assignments):
            raise ValueError(f"{slug}: reviewed language assignments do not cover every performed source")
    else:
        if (not isinstance(supplied_song_languages, list)
                or any(not isinstance(value, str) for value in supplied_song_languages)):
            raise ValueError("song languages must be a list of language names or codes")
        languages = list(dict.fromkeys(normalized_language(value) for value in supplied_song_languages
                                       if value.strip()))
    by_line_id = {}
    review_items = []
    for line_id, line in lines_by_id.items():
        explicit = (known_language(line["sourceLanguage"])
                    if "sourceLanguage" in line and line["sourceLanguage"] != "" else None)
        if line["source_text"] in assignments:
            code = assignments[line["source_text"]]
        elif explicit is not None:
            name, code = explicit
            if name not in languages:
                raise ValueError(f"{slug}:{line_id}: explicit line language is outside song languages")
        else:
            code = language_code(languages[0]) if len(languages) == 1 else ""
            if not code:
                review_items.append({"id": line_id,
                                     "reason": "No reviewed per-line language; song languages are multiple or undetermined."})
        by_line_id[line_id] = code
    return {"song_languages": languages, "by_line_id": by_line_id, "review_items": review_items}


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


def page_html(meta: dict[str, Any], slug: str) -> str:
    title = meta["title"]
    escape = lambda text: (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                           .replace('"', "&quot;").replace("'", "&#39;"))
    people: dict[str, list[str]] = {}
    for field, label in (("writer", str(meta.get("writerAttribution") or "Poet")),
                         ("translator", str(meta.get("translatorAttribution") or "Translation")),
                         ("singer", "Singer"), ("vocalist", "Vocalist"),
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
    canonical = f"{SITE_ORIGIN}/songs/{slug}/"
    subtitle = str(meta.get("subtitle") or "").strip()
    heading = f"{title} — {subtitle}" if subtitle else title
    performer = str(meta.get("singer") or meta.get("vocalist") or "").strip()
    song_asset_version = str(meta.get("songAssetVersion") or "tooltip-20261022-5")
    data_asset_version = str(meta.get("dataAssetVersion") or "contract-20260827-8")
    description = (f"{heading}: synchronised devotional lyrics with IAST transliteration, "
                   f"a literal English translation, and word-by-word meanings."
                   + (f" Sung by {performer}." if performer else ""))
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=2" />
  <meta name="theme-color" content="#6b0e16" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black" />
  <meta name="apple-mobile-web-app-title" content="Bhakti" />
  <link rel="icon" type="image/svg+xml" href="/assets/favicon.svg" />
  <link rel="apple-touch-icon" href="/assets/favicon.png" />
  <link rel="manifest" href="/manifest.webmanifest" />
  <link rel="canonical" href="{canonical}" />
  <meta name="description" content="{escape(description)}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Bhakti" />
  <meta property="og:title" content="{escape(heading)}" />
  <meta property="og:description" content="{escape(description)}" />
  <meta property="og:url" content="{canonical}" />
  <meta name="twitter:card" content="summary" />
  <meta name="referrer" content="no-referrer" />
  <title>{escape(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Cormorant+Garamond:ital,wght@0,300..700;1,300..700&family=EB+Garamond:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/style.css?v=contract-20260821-8" />
  <link rel="stylesheet" href="/assets/song.css?v=tooltip-20261022-5" />
  <link rel="stylesheet" href="/assets/site.css?v=ui-20261023-2" />
  <link rel="stylesheet" href="/assets/app.css?v=ui-20261023-2" />
</head>
<body data-app-view="song">
  <main class="song-page" id="songView">
    <header class="song-hero">
      <div class="song-top-controls" aria-label="Song controls">
        <button class="song-sync" id="songSync" type="button" aria-label="Keep lyrics synced to playback" aria-pressed="true" title="Lyrics follow playback"><svg class="sync-icon sync-icon-lock" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><use href="/assets/player-icons.svg#icon-lock"/></svg><svg class="sync-icon sync-icon-unlock" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><use href="/assets/player-icons.svg#icon-unlock"/></svg></button>
        <button class="song-share" id="songShare" type="button" aria-label="Share this song" title="Share"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 15.2V3.8m0 0L8.3 7.5M12 3.8l3.7 3.7M5 12.5v5.7c0 .99.81 1.8 1.8 1.8h10.4c.99 0 1.8-.81 1.8-1.8v-5.7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
      </div>
      <h1 class="song-title">{escape(title)}</h1>
{meta_html}      <p class="song-hint">Tap or hover over any word to see its meaning.</p>
    </header>
    <section class="song-root" id="songRoot" aria-live="polite"></section>
  </main>
  <div class="audio-player" id="audioPlayer">
    <a class="song-home app-view-toggle" id="appViewToggle" href="/" aria-label="Browse songs" title="Browse songs"><svg class="app-view-icon app-view-icon-home" viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><use href="/assets/player-icons.svg#icon-home"/></svg><svg class="app-view-icon app-view-icon-song" viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><use href="/assets/player-icons.svg#icon-music"/></svg></a>
    <button class="ap-btn" id="apPlayPause" type="button" aria-label="Play"><svg class="ap-icon ap-icon-play" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg><svg class="ap-icon ap-icon-pause" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor"/></svg></button>
    <div class="ap-progress" id="apProgress"><div class="ap-progress-bar" id="apProgressBar"></div></div>
    <div class="ap-time" id="apTime" aria-label="Playback time"><span id="apElapsed">0:00</span><span class="ap-time-sep">/</span><span class="ap-time-total" id="apDuration">—:—</span></div>
    <audio id="songAudio" preload="metadata">{source_html}</audio>
  </div>
  <script src="data.js?v={escape(data_asset_version)}"></script>
  <script src="/data/songs.js?v=contract-20260823-1"></script>
  <script src="/assets/queue.js?v=ui-20261023"></script>
  <script src="/assets/library.js?v=ui-20261023-2"></script>
  <script src="/assets/song.js?v=ui-20261023-3"></script>
  <script src="/assets/app.js?v=ui-20261023-3"></script>
  <script src="/assets/pwa.js?v=contract-20260827-9"></script>
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
        "queueId": hashlib.blake2s(song_dir.name.encode("utf-8"), digest_size=4).hexdigest(),
        "title": str(meta.get("title") or song_dir.name.replace("-", " ").title()),
        "credit": str(meta.get("credit") or ""),
        "languageTags": list(meta.get("languages") or []),
        "subjectTags": list(meta.get("subjectTags") or []),
        "searchAliases": list(meta.get("searchAliases") or []),
        "writer": str(meta.get("writer") or ""),
        "singer": str(meta.get("singer") or ""),
        "composer": str(meta.get("composer") or ""),
        "audioSources": list(meta.get("audioSources") or [{"src": "audio.m4a", "type": "audio/mp4"}]),
    }
    subtitle = str(meta.get("subtitle") or "").strip()
    if subtitle:
        entry["subtitle"] = subtitle
    return entry


QUEUE_NUMBERS_PATH = ROOT / "data" / "queue_numbers.json"


def assign_queue_numbers(slugs: list[str]) -> dict[str, int]:
    """Return a permanent slug -> small-integer map, appending only.

    Shared playlist links encode these numbers. A number is therefore assigned
    once and never reused or reordered: reassigning one would silently repoint
    every link that already contains it. New slugs take the next free integer,
    which keeps the numbering dense enough to bit-pack.
    """
    registry: dict[str, Any] = {"schemaVersion": 1, "numbers": {}}
    if QUEUE_NUMBERS_PATH.is_file():
        loaded = json.loads(QUEUE_NUMBERS_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not isinstance(loaded.get("numbers"), dict):
            raise RuntimeError(f"malformed queue number registry: {QUEUE_NUMBERS_PATH}")
        registry = loaded
    numbers: dict[str, int] = {str(k): int(v) for k, v in registry["numbers"].items()}
    if len(set(numbers.values())) != len(numbers):
        raise RuntimeError("queue number registry contains a duplicate number")
    next_number = max(numbers.values()) + 1 if numbers else 0
    for slug in sorted(slugs):
        if slug not in numbers:
            numbers[slug] = next_number
            next_number += 1
    if numbers != {str(k): int(v) for k, v in registry["numbers"].items()}:
        QUEUE_NUMBERS_PATH.write_text(
            json.dumps({"schemaVersion": 1, "numbers": dict(sorted(numbers.items()))},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return numbers


def write_catalogue() -> None:
    catalogue: list[dict[str, Any]] = []
    for song_dir in sorted((ROOT / "songs").glob("*")):
        if not song_dir.is_dir():
            continue
        meta = load_song_meta(song_dir)
        if not meta:
            continue
        catalogue.append(catalogue_entry(song_dir, meta))
    queue_ids = [entry["queueId"] for entry in catalogue]
    if len(queue_ids) != len(set(queue_ids)):
        raise RuntimeError("catalogue queueId collision")
    queue_numbers = assign_queue_numbers([entry["slug"] for entry in catalogue])
    for entry in catalogue:
        entry["queueNumber"] = queue_numbers[entry["slug"]]
    catalogue.sort(key=catalogue_sort_key)
    (ROOT / "data" / "songs.js").write_text(
        "window.BHAKTI_SONGS = " + json.dumps(catalogue, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    write_sitemap(entry["slug"] for entry in catalogue)


def write_sitemap(slugs: Any) -> None:
    """Keep sitemap.xml in step with the catalogue so every song page is discoverable."""
    urls = [f"{SITE_ORIGIN}/"] + [f"{SITE_ORIGIN}/songs/{slug}/" for slug in slugs]
    body = "".join(f"  <url><loc>{url}</loc></url>\n" for url in urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</urlset>\n",
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
    errors.extend(timing_uncertainty_errors(timing))
    if audited["packet"].get("uncertainties"):
        errors.append("audited transcription has unresolved uncertainties")
    if any(str(row.get("uncertainty") or "").strip().casefold() not in {"", "none", "no", "null", "n/a"}
           for row in gloss_rows + translation_rows):
        errors.append("gloss or translation has unresolved uncertainty")
    return errors


def reviewed_composite_metadata(job: dict[str, Any], sequence_length: int) -> tuple[list[dict[str, Any]], list[int]]:
    """Validate manual, source-backed notices for a composite liturgy.

    Models do not infer public provenance or adaptations.  A researched intake
    manifest may carry these small display notices, and invalid indices must
    fail generation rather than silently attaching a notice to another line.
    """
    notices = job.get("sectionNotices", [])
    adapted = job.get("adaptedSequenceIndices", [])
    if not isinstance(notices, list):
        raise RuntimeError("sectionNotices must be a list")
    if not isinstance(adapted, list):
        raise RuntimeError("adaptedSequenceIndices must be a list")
    cleaned_notices: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for index, notice in enumerate(notices):
        if not isinstance(notice, dict):
            raise RuntimeError(f"sectionNotices[{index}] must be an object")
        sequence_index = notice.get("sequenceIndex")
        title = str(notice.get("title") or "").strip()
        poet = notice.get("poet", "")
        note = notice.get("note", "")
        if (not isinstance(sequence_index, int) or not 0 <= sequence_index < sequence_length
                or sequence_index in seen_indices or not title
                or not isinstance(poet, str) or not isinstance(note, str)):
            raise RuntimeError(f"sectionNotices[{index}] is invalid for the reviewed sequence")
        seen_indices.add(sequence_index)
        cleaned_notices.append({"sequenceIndex": sequence_index, "title": title,
                                "poet": poet.strip(), "note": note.strip()})
    cleaned_adapted = sorted(set(adapted))
    if any(not isinstance(index, int) or not 0 <= index < sequence_length for index in cleaned_adapted):
        raise RuntimeError("adaptedSequenceIndices contains an invalid reviewed sequence index")
    return cleaned_notices, cleaned_adapted


def reviewed_line_labels(job: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, str]:
    labels = job.get("lineLabels", {})
    if not isinstance(labels, dict):
        raise RuntimeError("lineLabels must be an object")
    valid_ids = {str(line.get("id")) for line in lines}
    cleaned: dict[str, str] = {}
    for line_id, label in labels.items():
        text = str(label).strip()
        if not isinstance(line_id, str) or line_id not in valid_ids or not text:
            raise RuntimeError(f"lineLabels has an invalid entry for {line_id!r}")
        cleaned[line_id] = text
    return cleaned


def generate(song_dir: Path, job: dict[str, Any], source: dict[str, Any], audited: dict[str, Any], timing: dict[str, Any], glosses: dict[str, Any], translations: dict[str, Any], *, write_catalogue_after: bool = True) -> None:
    bhakti_semantic_repair.require_acceptance(sys.modules[__name__], song_dir / '.transcription/pipeline', glosses, translations, audited=audited)
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
    translator = naming.canonical_person(job.get("translator", ""))
    translator_attribution = str(job.get("translatorAttribution", "")).strip()
    writer_attribution = str(job.get("writerAttribution", "")).strip()
    singer = naming.canonical_person(job.get("singer") or source.get("artist") or "")
    vocalist = naming.canonical_person(job.get("vocalist", ""))
    composer = naming.canonical_person(job.get("composer") or source.get("composer") or "")
    ensemble = str(job.get("ensemble") or "").strip()
    distinct_people = list(dict.fromkeys(person for person in (writer, translator, singer, composer) if person))
    credit = str(job.get("credit", "")).strip() or " · ".join(distinct_people)
    page_credit = str(job.get("pageCredit", "")).strip() or singer or credit
    subjects = tag_taxonomy.merge_subject_tags(job.get("subjectTags", []), lines)
    subtitle = str(job.get("subtitle", "")).strip() or (subjects[0] if subjects else "")
    language_resolution = resolve_reviewed_languages(
        song_dir.name, lines, timing["sequence"],
        job.get("languages") or meta_from_model.get("languages", []), root=ROOT,
    )
    languages = language_resolution["song_languages"]
    aliases = naming.search_aliases(
        [job["slug"].replace("-", " "), title, subtitle, credit, page_credit,
         writer, translator, singer, vocalist, composer, ensemble, *subjects, *languages],
        [*naming.person_search_aliases((job.get("writer"), job.get("translator"), job.get("singer"), job.get("vocalist"), job.get("composer"), writer, translator, singer, vocalist, composer)),
         *(job.get("searchAliases") or [])],
    )
    meta = {"title": title, "subtitle": subtitle, "credit": credit, "pageCredit": page_credit,
            "writer": writer, "writerAttribution": writer_attribution,
            "translator": translator, "translatorAttribution": translator_attribution,
            "singer": singer, "vocalist": vocalist, "composer": composer, "ensemble": ensemble,
            "languages": languages,
            "subjectTags": subjects, "searchAliases": aliases,
            "audioSources": published_audio_sources(song_dir),
            "timingStatus": "start-only-reviewed",
            "translationStatus": "gloss-derived literal",
            "sourceStatus": "reviewed"}
    for version_field in ("songAssetVersion", "dataAssetVersion"):
        if job.get(version_field):
            meta[version_field] = str(job[version_field])
    line_data: dict[str, Any] = {}
    structural_markers: dict[str, str] = {}
    for line_index, line in enumerate(lines):
        line_id = line["id"]
        row = translation_by_id[line_id]
        words = [gloss_policy.clean_word({**word, "roman": naming.canonical_iast(word.get("roman", ""))})
                 for word in gloss_by_id[line_id].get("word_glosses", [])]
        source = line.get("source_text", "")
        source_has_verse_marker = has_terminal_verse_marker(source)
        marker_title, display_source, marker_pattern = metrical_prefix(display_source_without_verse_marker(source))
        display_roman = naming.canonical_iast(line.get("roman", ""))
        hidden_word_indices: set[int] = set()
        roman_prefix = None
        if marker_pattern is DOHA_PREFIX_SOURCE:
            structural_markers[line_id] = " ".join(filter(None, (marker_title, nearby_dohā_number(lines, line_index))))
            roman_prefix = DOHA_PREFIX_ROMAN
        elif marker_pattern is CHHAND_PREFIX_SOURCE:
            structural_markers[line_id] = marker_title
            roman_prefix = CHHAND_PREFIX_ROMAN
        elif marker_pattern is SORATHA_PREFIX_SOURCE:
            structural_markers[line_id] = marker_title
            roman_prefix = SORATHA_PREFIX_ROMAN
        if roman_prefix is not None:
            display_roman = roman_prefix.sub("", display_roman, count=1)
            if words:
                # A printed marker may share a token with the first sung word.
                words[0]["roman"] = roman_prefix.sub("", words[0]["roman"], count=1)
                if not words[0]["roman"].strip():
                    hidden_word_indices.add(0)
                else:
                    words[0]["gloss"] = re.sub(
                        r"^\s*(?:doh[āa]|chhand|sorath[āa])\s*(?:marker|tag)?\s*[:+]\s*",
                        "", words[0].get("gloss", ""), count=1, flags=re.I)
                    words[0] = gloss_policy.clean_word(words[0])
        index_map = {old: new for new, old in enumerate(index for index in range(len(words))
                                                          if index not in hidden_word_indices)}
        words = [word for index, word in enumerate(words) if index not in hidden_word_indices]
        remapped_parts = []
        for part in row.get("segments", []):
            if marker_title and re.fullmatch(r"\s*(?:doh[āa]|chhand|sorath[āa])[.:]?\s*",
                                            str(part.get("text", "")), flags=re.I):
                continue
            original_indices = [index for index in part.get("word_indices", []) if isinstance(index, int)]
            indices = [index_map[index] for index in original_indices if index in index_map]
            if original_indices and not indices:
                continue
            remapped_parts.append({**part, "word_indices": indices})
        marker_indexes = {index for index, word in enumerate(words)
                          if re.fullmatch(r"[0-9]+", str(word.get("roman", "")).strip())}
        source_words = [mapping for mapping in source_word_map.build_source_words(display_source, words)
                        if not (set(mapping.get("wordIndices", [])).issubset(marker_indexes)
                                or (source_has_verse_marker
                                    and re.fullmatch(r"[०-९0-9]+", str(mapping.get("text", "")).strip())))]
        english_parts = [part for part in remapped_parts
                         if not is_verse_marker_english_segment(part.get("text"))]
        if source_has_verse_marker and english_parts:
            english_parts = [dict(part) for part in english_parts]
            english_parts[-1]["text"] = strip_terminal_verse_marker_english(english_parts[-1].get("text"))
        english_fallback = strip_terminal_verse_marker_english(row.get("literal_english", ""))
        line_data[line_id] = {"source": display_source, "sourceLanguage": language_resolution["by_line_id"][line_id],
                              "sourceWords": source_words,
                              "roman": display_roman_without_verse_marker(display_roman, source), "english": segment_english(english_parts, english_fallback),
                              "words": words,
                              "nameTable": bool(line.get("name_table")),
                              "grammarNote": naming.canonical_iast(gloss_by_id[line_id].get("grammar_note", ""))}
        line_data[line_id], marker_cleanup = clean_display_word_map(line_data[line_id])
        if marker_cleanup["unlinkedEnglish"]:
            write_json(song_dir / ".transcription" / "display-word-map" / f"{line_index:04d}.json",
                       {"line_id": line_id, **marker_cleanup})
    if structural_markers:
        meta["structuralMarkers"] = structural_markers
    sequence = [{"ref": event["ref"],
                 "section": event.get("section") or next((line.get("kind", "verse")
                                                           for line in lines if line["id"] == event["ref"]), "verse"),
                 "repeats": int(event.get("repeats", 1) or 1)}
                for event in timing["sequence"]]
    times = [{"start": round(event["start"], 3), "end": round(event["end"], 3)} for event in timing["sequence"]]
    sequence, times, _ = compress_adjacent_reader_entries(sequence, times)
    notices, adapted_indices = reviewed_composite_metadata(job, len(sequence))
    if notices:
        meta["sectionNotices"] = notices
    if adapted_indices:
        meta["adaptedSequenceIndices"] = adapted_indices
    labels = reviewed_line_labels(job, lines)
    if labels:
        meta["lineLabels"] = labels
    scripture_metadata.apply(meta, song_dir.name, sequence)
    tag_taxonomy.apply_reviewed_subject_tags(meta, song_dir.name, line_data, sequence, root=ROOT)
    data = ("window.SONG_META = " + json.dumps(meta, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_LINES = " + json.dumps(line_data, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_SEQUENCE = " + json.dumps(sequence, ensure_ascii=False, indent=2) + ";\n\n" +
            "window.SONG_TIMINGS = " + json.dumps(times, ensure_ascii=False, indent=2) + ";\n")
    editorial_baselines.assert_english_preserved(song_dir.name, line_data, root=ROOT)
    write_json(song_dir / ".transcription" / "language-review.json", language_resolution)
    (song_dir / "data.js").write_text(data, encoding="utf-8")
    (song_dir / "index.html").write_text(page_html(meta, song_dir.name), encoding="utf-8")
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
    if options.generate_only:
        return None
    if gemini.provider_name() == "together":
        return (
            "Together text processing is configured, but the sung-Punjabi audio "
            "qualification failed coverage checks. Full intake remains blocked; "
            "see docs/TOGETHER_AUDIO_QUALIFICATION.md. Text-only review can use "
            "scripts/audit_translation_style.py; reviewed artifacts can use --generate-only."
        )
    if gemini.provider_name() != "openrouter":
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


def language_hold_packet(song_dir: Path, source: dict[str, Any], raw: dict[str, Any], started: float,
                         trim: dict[str, Any] | None = None) -> dict[str, Any]:
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
        "trim": trim,
        "reported_cost_scope": "accepted-artifacts-only; bounded ledger is authoritative for charges",
        "reported_openrouter_cost": reported_cost(raw, trim),
    }
    write_json(song_dir / ".transcription" / "pipeline" / "song-packet.json", packet)
    return packet


def hydrate_pipeline_artifacts(packet_dir: Path) -> None:
    summary = read_packet(packet_dir / "song-packet.json") or {}
    glosses = read_packet(packet_dir / '04-glosses.json') or summary.get('glosses')
    translations = read_packet(packet_dir / '05-translation.json') or summary.get('translation')
    bhakti_semantic_repair.require_acceptance(sys.modules[__name__], packet_dir, glosses, translations, summary)
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


def require_trim_adoption(song_dir: Path, artifact: dict[str, Any]) -> None:
    """Hold changed historical audio before it can acquire stale cached text/times.

    This is a temporary caller guard, not the historical adoption operation.
    Fresh intake and unchanged original/applied intervals remain permitted.
    """
    packet_dir = song_dir / ".transcription" / "pipeline"
    dependencies = [song_dir / "data.js", *(packet_dir / name for name in (
        "01-transcript.json", "02-transcript-audit.json", "03-timing.json", "song-packet.json"))]
    if not any(path.exists() for path in dependencies):
        return
    normalized = normalize_trim_artifact(artifact)
    if normalized["validation_errors"] or normalized["status"] != "reviewed":
        raise RuntimeError("historical trim adoption cannot use unresolved boundary evidence")
    marker = read_packet(song_dir / ".transcription" / "trim-applied.json") or {}
    same = (marker.get("application_version") == 2 and marker.get("status") in {"applied", "no-trim"}
            and marker.get("source_sha256") == normalized["source_sha256"]
            and marker.get("trim_start") == normalized["trim_start"]
            and marker.get("trim_end") == normalized["trim_end"])
    if same:
        return  # Application still verifies every current output digest.
    whole = normalized["trim_start"] <= 0.001 and normalized["trim_end"] >= normalized["duration"] - 0.001
    current = song_dir / normalized["source_audio"]
    still_original = (current.is_file() and hashlib.sha256(current.read_bytes()).hexdigest() == normalized["source_sha256"])
    manifest = read_packet(song_dir / ".transcription" / "trim-originals.json") or {}
    if manifest:
        still_original = still_original and all(
            (song_dir / row["src"]).is_file() and hashlib.sha256((song_dir / row["src"]).read_bytes()).hexdigest() == row["sha256"]
            for row in manifest.get("sources", []))
    if whole and still_original and marker.get("status") != "pending":
        return
    raise RuntimeError("historical trim adoption required before changing audio used by cached source/timing or a public reader")


def run_one(job: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    song_dir, source = intake(job, force=options.force)
    started = time.time()
    trim = detect_youtube_trim(song_dir, source, options)
    require_trim_adoption(song_dir, trim)
    apply_lossless_trim(song_dir, trim)
    audio = preferred_listener_audio(song_dir)
    raw = transcript(song_dir, source, audio, options)
    if job.get("holdIfSanskrit") and is_sanskrit_first_pass(raw):
        packet = language_hold_packet(song_dir, source, raw, started, trim)
        return {"slug": job["slug"], "status": packet["publication_status"],
                "elapsed_seconds": packet["elapsed_seconds"],
                "reported_openrouter_cost": packet["reported_openrouter_cost"],
                "reported_cost_scope": packet["reported_cost_scope"]}
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
    glosses, translations = complete_semantics(song_dir, audited, job, options)
    errors = publication_errors(audited, timing, glosses, translations)
    status = "blocked" if errors else "review-required"
    packet = {"source": source, "model_requested": options.model, "created_at": time.time(), "transcript": raw,
              "audit": audited, "timing": timing, "glosses": glosses, "translation": translations,
              "publication_status": status, "validation_errors": errors,
              "elapsed_seconds": round(time.time() - started, 2),
              "trim": trim, "reported_openrouter_cost": reported_cost(trim, raw, audited, timing, glosses, translations),
              "reported_cost_scope": "accepted-artifacts-only; bounded ledger is authoritative for charges"}
    write_json(song_dir / ".transcription" / "pipeline" / "song-packet.json", packet)
    return {"slug": job["slug"], "status": packet["publication_status"], "elapsed_seconds": packet["elapsed_seconds"],
            "reported_openrouter_cost": packet["reported_openrouter_cost"],
                "reported_cost_scope": packet["reported_cost_scope"]}


def main() -> int:
    from bhakti_intake_run import bounded_intake_run
    options = parse_args()
    if options.economy:
        options.model = economy_model(options.model)
    jobs = normalise_jobs(options)
    with bounded_intake_run(ROOT, jobs, options):
        return _execute_intake_jobs(options, jobs)


def _execute_intake_jobs(options: argparse.Namespace, jobs: list[dict[str, Any]]) -> int:
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
            try:
                hydrate_pipeline_artifacts(packet_dir)
                source = read_packet(song_dir / ".transcription" / "source.json") or {}
                audited = read_packet(packet_dir / "02-transcript-audit.json")
                timing = read_packet(packet_dir / "03-timing.json")
                glosses = read_packet(packet_dir / "04-glosses.json")
                translations = read_packet(packet_dir / "05-translation.json")
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
