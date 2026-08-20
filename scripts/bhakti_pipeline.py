#!/usr/bin/env python3
"""Build reviewed Bhakti readers from local audio or YouTube URLs.

This is the production intake command.  It deliberately separates the model
jobs which were previously interleaved in ad-hoc song work:

  1. complete transcription, 2. transcript audit, 3. lyric-aware timing,
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
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]
MODEL = gemini.MODEL
WINDOW_SECONDS = 52.0
OVERLAP_SECONDS = 3.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--song", action="append", default=[], metavar="SLUG=SOURCE",
                        help="Local audio path or yt-dlp URL. Repeat for a batch.")
    parser.add_argument("--batch", type=Path,
                        help="JSON: {songs:[{slug, source, title?, credit?, languages?, subjectTags?, subtitle?}]}")
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


def normalise_jobs(options: argparse.Namespace) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for spec in options.song:
        if "=" not in spec:
            raise SystemExit("--song must be SLUG=SOURCE")
        slug, source = spec.split("=", 1)
        jobs.append({"slug": slug.strip(), "source": source.strip()})
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
        metadata_raw = subprocess.run(
            ["yt-dlp", "--no-playlist", "--dump-single-json", "--skip-download", source_value],
            check=True, capture_output=True, text=True,
        ).stdout
        metadata = json.loads(metadata_raw)
        source = {
            "source_url": metadata.get("webpage_url") or source_value,
            "title": metadata.get("title"), "uploader": metadata.get("uploader"),
            "channel": metadata.get("channel"), "upload_date": metadata.get("upload_date"),
            "duration_seconds": metadata.get("duration"), "description": metadata.get("description"),
            "extractor_key": metadata.get("extractor_key"), "id": metadata.get("id"),
            "review_note": "Source metadata is evidence to verify, never automatic public credit.",
        }
        subprocess.run(["yta", source_value, "--output-dir", str(song_dir)], check=True)
        downloads = list(song_dir.glob("*.m4a"))
        if len(downloads) != 1:
            raise RuntimeError(f"expected one M4A from {source_value}, found {len(downloads)}")
        downloads[0].replace(audio)
    else:
        supplied = Path(source_value).expanduser().resolve()
        if not supplied.is_file():
            raise RuntimeError(f"audio source does not exist: {supplied}")
        if supplied.suffix.casefold() == ".m4a":
            shutil.copy2(supplied, audio)
        else:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(supplied),
                            "-vn", "-c:a", "aac", "-b:a", "192k", str(audio)], check=True)
        source = {"source_file": supplied.name, "title": supplied.stem,
                  "review_note": "Local file metadata is evidence to verify, never automatic public credit."}
    write_json(review_dir / "source.json", source)
    return song_dir, source


def ask(prompt: str, audio: Path | None, options: argparse.Namespace) -> dict[str, Any]:
    return gemini.call(options.model, gemini.key(), prompt, audio=audio, timeout=options.timeout)


def transcript(song_dir: Path, source: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "01-transcript.json"
    existing = read_packet(target)
    if existing and not options.force:
        return existing
    prompt = f"""Transcribe this complete devotional recording exactly. Listen from beginning to end.

Do not translate. Do not omit any sung, spoken, call-and-response, invocation, refrain, pickup, return, or closing line. Do not infer repetition counts: list every performance occurrence in order. Use the appropriate source script whenever known and careful romanization. Unknown words or credits must be marked uncertain rather than invented.

Source metadata is only a lead, not proof of public credits:
{json.dumps(source, ensure_ascii=False)}

Return strict JSON:
{{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"lines":[{{"id":"stable-kebab-id","source_text":"","roman":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"stable-kebab-id","occurrence":1,"notes":""}}],"uncertainties":[]}}"""
    result = ask(prompt, audio, options)
    write_json(target, result)
    return result


def audit_transcript(song_dir: Path, raw: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "02-transcript-audit.json"
    existing = read_packet(target)
    if existing and not options.force:
        return existing
    prompt = f"""Audit the candidate transcript against this complete devotional recording. This is a transcription-verification task, not timing.

Correct every missed, duplicated, reordered, or misheard lyric. Preserve every audible performance occurrence in exact order, including lead pickups before answers and later returns. Do not translate or estimate timestamps. If any content remains unclear, put it in uncertainties; do not silently guess.

Candidate transcript:
{json.dumps(raw['packet'], ensure_ascii=False)}

Return strict JSON:
{{"metadata":{{"languages":[],"script":"","singer_candidates":[],"credit_evidence":[]}},"verified_lines":[{{"id":"stable-kebab-id","source_text":"","roman":"","kind":"invocation|refrain|verse|bridge|closing|spoken|instrumental|uncertain","notes":""}}],"performance_order":[{{"line_id":"stable-kebab-id","occurrence":1,"notes":""}}],"changes":[],"uncertainties":[]}}"""
    result = ask(prompt, audio, options)
    write_json(target, result)
    return result


def make_windows(audio: Path, duration: float, destination: Path) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    core_start = 0.0
    index = 0
    while core_start < duration - 0.01:
        start = max(0.0, core_start - OVERLAP_SECONDS)
        end = min(duration, core_start + WINDOW_SECONDS + OVERLAP_SECONDS)
        path = destination / f"window-{index:03d}.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(audio),
                        "-t", f"{end - start:.3f}", "-vn", "-c:a", "aac", "-b:a", "128k", str(path)], check=True)
        windows.append({"index": index, "start": start, "end": end, "core_start": core_start,
                        "core_end": min(duration, core_start + WINDOW_SECONDS), "path": path})
        core_start += WINDOW_SECONDS
        index += 1
    return windows


def timing_window(window: dict[str, Any], lines: list[dict[str, Any]], options: argparse.Namespace) -> dict[str, Any]:
    length = window["end"] - window["start"]
    prompt = f"""Precisely align this short excerpt of one devotional recording to its audited lyric catalogue. The excerpt begins at source second {window['start']:.3f} and ends at {window['end']:.3f}. Return times relative to this excerpt, not source time.

For each entry, `start` MUST be the first audible syllable of that displayed line—never the response, chorus, backing voice, or middle clause. Include `first_words`, the heard opening words that anchor the time. Map only exact canonical ids. An incomplete phrase caused by the excerpt boundary belongs in `boundary_fragments`; any other unmatched vocal belongs in `unmatched` and blocks publication.

Audited catalogue:
{json.dumps(lines, ensure_ascii=False)}

Return strict JSON:
{{"events":[{{"ref":"canonical-id","start":0.0,"end":0.0,"first_words":"","confidence":"high|medium|low"}}],"boundary_fragments":[{{"start":0.0,"end":0.0,"heard":""}}],"unmatched":[{{"start":0.0,"end":0.0,"heard":"","reason":""}}]}}"""
    response = ask(prompt, window["path"], options)
    return {"window": {k: v for k, v in window.items() if k != "path"}, "response": response}


def dedupe_timing(events: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    # Each first vocal onset belongs to precisely one non-overlapping core.
    # Context overlap is only for hearing a boundary clearly; averaging two
    # model timestamps would itself move a first-syllable onset.
    events.sort(key=lambda event: event["start"])
    for index, event in enumerate(events):
        event["end"] = events[index + 1]["start"] if index + 1 < len(events) else duration
        event["anchors"] = [event["first_words"]]
        event["confidence"] = [event["confidence"]]
    return events


def align(song_dir: Path, audited: dict[str, Any], audio: Path, options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "03-timing.json"
    existing = read_packet(target)
    if existing and not options.force:
        return existing
    packet = audited["packet"]
    lines = packet.get("verified_lines", [])
    expected = [entry.get("line_id") for entry in packet.get("performance_order", [])]
    duration = gemini.duration_seconds(audio)
    if not lines or not expected or any(not isinstance(ref, str) for ref in expected):
        raise RuntimeError("audited transcript lacks canonical lines or performance order")
    output_dir = target.parent / "timing-windows"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-timing-") as temp:
        windows = make_windows(audio, duration, Path(temp))
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(windows))) as pool:
            artifacts = list(pool.map(lambda window: timing_window(window, lines, options), windows))
    events: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for artifact in artifacts:
        number = artifact["window"]["index"]
        write_json(output_dir / f"window-{number:03d}.json", artifact)
        response = artifact["response"]["packet"]
        for raw in response.get("events", []):
            try:
                start = artifact["window"]["start"] + float(raw["start"])
                end = artifact["window"]["start"] + float(raw["end"])
                ref = raw["ref"]
                if ref not in expected or not 0 <= start <= end <= duration:
                    raise ValueError("invalid ref or range")
                # A window's overlap provides listening context, but only its
                # core owns the event. This prevents a line at a chunk boundary
                # from being merged, averaged, or counted as a second return.
                if not artifact["window"]["core_start"] - 0.001 <= start < artifact["window"]["core_end"] - 0.001:
                    continue
                events.append({"ref": ref, "start": start, "end": end, "first_words": str(raw.get("first_words", "")),
                               "confidence": str(raw.get("confidence", "low")), "window": number})
            except (KeyError, TypeError, ValueError):
                unmatched.append({"window": number, "event": raw, "reason": "invalid timing event"})
        unmatched.extend({"window": number, "event": raw, "reason": "unmatched vocal"} for raw in response.get("unmatched", []))
    merged = dedupe_timing(events, duration)
    observed = [entry["ref"] for entry in merged]
    errors: list[str] = []
    if observed != expected:
        errors.append(f"timing sequence differs from audited performance order: expected {expected}, got {observed}")
    if unmatched:
        errors.append("timing model reported non-boundary unmatched vocal material")
    low = [entry["ref"] for entry in merged if "low" in entry["confidence"] or not entry["anchors"][-1].strip()]
    if low:
        errors.append(f"low-confidence or unanchored first-syllable timing: {', '.join(low)}")
    result = {"duration_seconds": duration, "expected_order": expected, "sequence": merged, "unmatched": unmatched,
              "validation_errors": errors, "publication_status": "blocked" if errors else "review-required"}
    write_json(target, result)
    return result


def gloss(song_dir: Path, audited: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "04-glosses.json"
    existing = read_packet(target)
    if existing and not options.force:
        return existing
    lines = audited["packet"].get("verified_lines", [])
    prompt = f"""Create a literal word-by-word reading of these audited devotional lyrics. Work line by line.

Segment each source line into actual words or meaningful grammatical units. Give a concise literal gloss for every unit and a short grammar note for idiom, ellipsis, agreement, or syntax. Preserve imagery and uncertainty. Do not write a fluent English sentence in this stage.

Lyrics:
{json.dumps(lines, ensure_ascii=False)}

Return strict JSON:
{{"glosses":[{{"id":"canonical-id","word_glosses":[{{"roman":"exact token","gloss":"literal meaning"}}],"grammar_note":"","uncertainty":""}}]}}"""
    result = ask(prompt, None, options)
    write_json(target, result)
    return result


def supplied_translation(job: dict[str, Any]) -> str:
    value = job.get("providedTranslation", job.get("provided_translation", ""))
    if not value:
        return "(none supplied)"
    possible_path = Path(str(value)).expanduser()
    return possible_path.read_text(encoding="utf-8") if possible_path.is_file() else str(value)


def translate(song_dir: Path, audited: dict[str, Any], glosses: dict[str, Any], job: dict[str, Any], options: argparse.Namespace) -> dict[str, Any]:
    target = song_dir / ".transcription" / "pipeline" / "05-translation.json"
    existing = read_packet(target)
    if existing and not options.force:
        return existing
    prompt = f"""Write faithful, complete, idiomatic English translations from the supplied word glosses and grammar notes ONLY. The glosses are semantic constraints, not a license for wooden word-for-word substitution: preserve their exact meaning, grammar, poetic image, register, and all emphases while writing natural English. Do not introduce a looser synonym, devotional interpretation, or omission that the gloss record does not support. Equally, do not replace a precise English image with a blander gloss synonym merely because it is shorter.

For each line, return plain literal English plus ordered display segments. Each segment may reference the exact word indices which support it; punctuation or function-word segments can use an empty index list. Preserve poetic imagery without making the literal sentence more poetic than its glosses warrant. Report uncertainty honestly.

Audited source lines:
{json.dumps(audited['packet'].get('verified_lines', []), ensure_ascii=False)}

Word gloss record:
{json.dumps(glosses['packet'].get('glosses', []), ensure_ascii=False)}

Supplied translation, if any (a comparison witness, never an automatic
baseline or disposable raw material):
{supplied_translation(job)}

Return strict JSON:
{{"translations":[{{"id":"canonical-id","literal_english":"","segments":[{{"text":"","word_indices":[]}}],"uncertainty":""}}],"comparison":[{{"id":"canonical-id","supplied":"","chosen":"","material_change":false,"reason":""}}]}}"""
    result = ask(prompt, None, options)
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
    errors: list[str] = []
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
        cursor = 0
        folded = roman.casefold()
        for index, word in enumerate(words):
            token = str(word.get("roman", "")).strip()
            gloss = str(word.get("gloss", "")).strip()
            at = folded.find(token.casefold(), cursor) if token else -1
            if not token or not gloss or at < 0:
                errors.append(f"{line_id} word gloss {index} cannot be mapped to romanized source")
                break
            cursor = at + len(token)
        translation = translation_by_id.get(line_id, {})
        if not str(translation.get("literal_english", "")).strip():
            errors.append(f"{line_id} lacks a literal English line")
        for segment in translation.get("segments", []):
            for word_index in segment.get("word_indices", []):
                if not isinstance(word_index, int) or not 0 <= word_index < len(words):
                    errors.append(f"{line_id} English segment uses invalid word index {word_index!r}")
    return errors


def segment_english(parts: list[dict[str, Any]], fallback: str) -> str:
    if not parts:
        return fallback
    rendered: list[str] = []
    for part in parts:
        text = str(part.get("text", ""))
        indices = [str(index) for index in part.get("word_indices", []) if isinstance(index, int) and index >= 0]
        rendered.append("{" + ",".join(indices) + ":" + text + "}" if indices else text)
    return "".join(rendered)


def language_code(language: str) -> str:
    return {"Hindi": "hi", "Sanskrit": "sa", "Punjabi": "pa", "Kannada": "kn"}.get(language, "")


def page_html(meta: dict[str, Any]) -> str:
    title = meta["title"]
    credit = meta.get("pageCredit") or meta.get("credit", "")
    subtitle = meta.get("subtitle", "")
    escape = lambda text: str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sub = f'      <p class="song-attrib"><em>{escape(subtitle)}</em></p>\n' if subtitle else ""
    cred = f'      <p class="song-credit">{escape(credit)}</p>\n' if credit else ""
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
    <button class="ap-btn" id="apPlayPause" type="button" aria-label="Play"><svg class="ap-icon ap-icon-play" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg><svg class="ap-icon ap-icon-pause" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor"/></svg></button>
    <div class="ap-progress" id="apProgress"><div class="ap-progress-bar" id="apProgressBar"></div></div>
    <audio id="songAudio" preload="metadata"><source src="audio.m4a" type="audio/mp4"></audio>
  </div>
  <script src="data.js?v=contract-20260820"></script>
  <script src="../../assets/song.js?v=contract-20260820"></script>
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
    if any(row.get("uncertainty") for row in gloss_rows + translation_rows):
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
    title = job.get("title") or source.get("title") or job["slug"].replace("-", " ").title()
    # Do not manufacture a public role from a model candidate. Callers may
    # supply researched roles; otherwise the compact credit line is absent.
    writer = str(job.get("writer", "")).strip()
    singer = str(job.get("singer", "")).strip()
    composer = str(job.get("composer", "")).strip()
    distinct_people = list(dict.fromkeys(person for person in (writer, singer, composer) if person))
    credit = str(job.get("credit", "")).strip() or " · ".join(distinct_people)
    page_credit = str(job.get("pageCredit", "")).strip() or singer or credit
    subjects = job.get("subjectTags", [])
    subtitle = str(job.get("subtitle", "")).strip() or (subjects[0] if subjects else "")
    meta = {"title": title, "subtitle": subtitle, "credit": credit, "pageCredit": page_credit,
            "writer": writer, "singer": singer, "composer": composer,
            "languages": job.get("languages") or meta_from_model.get("languages", []),
            "subjectTags": subjects, "translationStatus": "gloss-derived literal",
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
    entry = {"slug": job["slug"], "title": title, "credit": credit, "languageTags": meta["languages"], "subjectTags": meta["subjectTags"]}
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
    audio = song_dir / "audio.m4a"
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
