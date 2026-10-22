#!/usr/bin/env python3
"""Prepare a deterministic, private repair inventory; never call a model or edit readers.

The committed catalogue defines membership. Working reader bytes are inspected
and hashed, so unrelated local intake cannot silently expand the published set.
Routes identify the next kind of review, not correctness or publication approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import audit_bhakti_contract as contract


ROOT = Path(__file__).resolve().parents[1]
STAGES = ("01-transcript.json", "02-transcript-audit.json", "03-timing.json",
          "04-glosses.json", "05-translation.json", "song-packet.json")
TRANSLATION_FIELDS = ("humanTranslation", "human_translation", "providedTranslation", "provided_translation")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_digest(value: Any) -> str:
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                          capture_output=True).stdout


def committed_bytes(root: Path, revision: str, path: str) -> bytes | None:
    try:
        return git(root, "show", f"{revision}:{path}")
    except subprocess.CalledProcessError:
        return None


def load_javascript(source: bytes) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm'),ctx={window:{}};
vm.runInNewContext(fs.readFileSync(0,'utf8'),ctx,{timeout:1000});
process.stdout.write(JSON.stringify(ctx.window));"""
    result = subprocess.run(["node", "-e", script], input=source, capture_output=True, check=True)
    return json.loads(result.stdout)


def artifact(root: Path, path: Path, *, hash_content: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path.relative_to(root).as_posix(), "exists": path.is_file()}
    if result["exists"]:
        result["bytes"] = path.stat().st_size
        if hash_content:
            result["sha256"] = digest(path.read_bytes())
    return result


def read_object(path: Path, defects: list[str]) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (OSError, ValueError) as exc:
        defects.append(f"invalid review artifact {path.name}: {type(exc).__name__}")
        return {}


def plain_english(value: Any) -> str:
    return re.sub(r"\{[\d,\s]+:([^}]*)\}", r"\1", str(value or ""))


def provenance_matches(reader: dict[str, Any], source: dict[str, Any], stages: dict[str, Any]) -> bool:
    """Only explicit baseline declarations plus matching stored state can unlock."""
    summary = stages.get("song-packet.json", {})
    audit = stages.get("02-transcript-audit.json", {})
    timing = stages.get("03-timing.json", {})
    translation = stages.get("05-translation.json", {})
    if not source or summary.get("source") != source:
        return False
    if any(summary.get(key) != stage for key, stage in
           (("audit", audit), ("timing", timing), ("translation", translation))):
        return False
    if not all(isinstance(stage.get("packet"), dict) for stage in (audit, translation)):
        return False
    if (audit["packet"].get("uncertainties") or timing.get("validation_errors")
            or timing.get("uncertain_occurrence_ids")):
        return False
    lines = reader.get("SONG_LINES", {})
    verified = audit["packet"].get("verified_lines", [])
    translations = translation["packet"].get("translations", [])
    if (not isinstance(lines, dict) or any(not isinstance(line, dict) for line in lines.values())
            or not isinstance(verified, list) or not isinstance(translations, list)
            or any(not isinstance(row, dict) for row in verified + translations)):
        return False
    if (len(verified) != len(lines) or {row.get("id") for row in verified} != set(lines)
            or len(translations) != len(lines) or {row.get("id") for row in translations} != set(lines)):
        return False
    for row in verified:
        current = lines[row["id"]]
        if row.get("source_text") != current.get("source") or row.get("roman") != current.get("roman"):
            return False
    for row in translations:
        if row.get("literal_english") != plain_english(lines[row["id"]].get("english")):
            return False
    sequence, points = reader.get("SONG_SEQUENCE", []), reader.get("SONG_TIMINGS", [])
    recorded = timing.get("sequence", [])
    if (not all(isinstance(rows, list) for rows in (recorded, sequence, points))
            or any(not isinstance(row, dict) for rows in (recorded, sequence, points) for row in rows)
            or len(recorded) != len(sequence) or len(sequence) != len(points)):
        return False
    return all(all(recorded[index].get(key) == row.get(key) for key in ("ref", "section", "repeats"))
               and all(recorded[index].get(key) == points[index].get(key) for key in ("start", "end"))
               for index, row in enumerate(sequence))


def translation_lock(meta: dict[str, Any], source: dict[str, Any], stages: dict[str, Any],
                     explicit: dict[str, Any], reader: dict[str, Any]) -> dict[str, Any]:
    if explicit:
        # Unknown registry policies also stay held; only preserve_english is supported.
        return {"status": "preserve_english", "evidence": "editorial_baselines",
                "record": explicit, "autoApply": False}
    summary = stages.get("song-packet.json", {})
    provenance_declarations = [obj[key] for obj in (source, summary.get("job", {}))
                              if isinstance(obj, dict) for key in TRANSLATION_FIELDS if key in obj]
    declarations = [obj[key] for obj in (meta, source, summary, summary.get("job", {}))
                    if isinstance(obj, dict) for key in TRANSLATION_FIELDS if key in obj]
    if any(value not in (None, "", False, "(none supplied)") for value in declarations):
        return {"status": "preserve_english", "evidence": "stored human/supplied translation",
                "autoApply": False}
    if provenance_declarations and provenance_matches(reader, source, stages):
        return {"status": "confirmed_unlocked", "evidence": "explicit empty supplied translation and matching saved provenance",
                "autoApply": False}
    return {"status": "unknown", "evidence": "no consistent explicit baseline declaration", "autoApply": False}


def folded(value: Any) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", str(value)).casefold()
                   if not unicodedata.combining(char))


def inspect_song(root: Path, revision: str, song: dict[str, Any], locks: dict[str, Any]) -> dict[str, Any]:
    slug = song["slug"]
    directory = root / "songs" / slug
    private = directory / ".transcription"
    data_path = directory / "data.js"
    defects: list[str] = []
    reader: dict[str, Any] = {}
    original = committed_bytes(root, revision, f"songs/{slug}/data.js")
    current = data_path.read_bytes() if data_path.is_file() else None
    if current is not None:
        try:
            reader = load_javascript(current)
            defects.extend(contract.audit_song(directory, song)["problems"])
        except (subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError) as exc:
            defects.append(f"reader inspection failed: {type(exc).__name__}")
    else:
        defects.append("missing published reader data.js")
    if not (directory / "index.html").is_file():
        defects.append("missing published reader index.html")
    meta = reader.get("SONG_META", {})
    meta = meta if isinstance(meta, dict) else {}
    lines = reader.get("SONG_LINES", {})
    lines = lines if isinstance(lines, dict) else {}
    sequence, timings = reader.get("SONG_SEQUENCE", []), reader.get("SONG_TIMINGS", [])
    sequence_is_list = isinstance(sequence, list)
    sequence = sequence if isinstance(sequence, list) else []
    timings = timings if isinstance(timings, list) else []
    for line_id, line in lines.items():
        if not isinstance(line, dict):
            continue
        english = str(line.get("english", ""))
        if re.search(r"[{}]", plain_english(english)):
            defects.append(f"{line_id} malformed English linkage braces")
        if any("\ufffd" in str(line.get(field, "")) for field in ("source", "roman", "english")):
            defects.append(f"{line_id} replacement character in reading text")
    if any(not isinstance(point, dict) or any(not isinstance(point.get(key), (int, float))
           or isinstance(point.get(key), bool) or not math.isfinite(point[key]) for key in ("start", "end"))
           for point in timings):
        defects.append("timing contains missing or non-finite numbers")
    repeated = [entry.get("repeats") for entry in sequence if isinstance(entry, dict)]
    performed_count = (sum(repeated) if sequence_is_list and len(repeated) == len(sequence)
                       and all(type(count) is int and count >= 1 for count in repeated) else None)
    source_path = private / "source.json"
    source = read_object(source_path, defects)
    stages = {name: read_object(private / "pipeline" / name, defects) for name in STAGES}
    pointers = {"reader": artifact(root, data_path), "page": artifact(root, directory / "index.html"),
                "source": artifact(root, source_path),
                "pipeline": {name: artifact(root, private / "pipeline" / name) for name in STAGES},
                "editorialPipeline": {name: artifact(root, private / "editorial-pipeline" / name)
                                      for name in STAGES if (private / "editorial-pipeline" / name).is_file()}}
    audio = [artifact(root, directory / f"audio{suffix}", hash_content=False)
             for suffix in (".webm", ".m4a", ".mp3", ".ogg", ".flac", ".wav")
             if (directory / f"audio{suffix}").is_file()]
    lock = translation_lock(meta, source, stages, locks.get(slug, {}), reader)
    review = ["literal meaning, imagery, agency and hover meanings require editorial review",
              "every performance occurrence and first-syllable onset require audio comparison"]
    if lock["status"] != "confirmed_unlocked":
        review.append("establish or preserve the human English baseline before any mutation")
    audio_reasons = [reason for reason in defects if re.search(
        r"source script|IAST|sequence|timing|repeated phrase|reader inspection|missing published reader|replacement character", reason)]
    if meta.get("sourceStatus") != "reviewed" or meta.get("timingStatus") != "start-only-reviewed":
        audio_reasons.append("stored source/timing review status is absent or incomplete")
    audit_packet = stages["02-transcript-audit.json"].get("packet", {})
    if not isinstance(audit_packet, dict):
        defects.append("invalid transcript audit packet object")
        audit_packet = {}
    if (audit_packet.get("uncertainties")
            or stages["03-timing.json"].get("validation_errors")
            or stages["03-timing.json"].get("uncertain_occurrence_ids")):
        audio_reasons.append("saved audio evidence contains unresolved uncertainties")
    dirty = original is None or current != original
    source_value = str(source.get("source_url") or source.get("source_path") or "")
    source_ready = bool(source_value and (urlparse(source_value).scheme == "https" or Path(source_value).is_file()))
    holds = []
    if dirty:
        holds.append("working reader differs from catalogue revision")
    if lock["status"] != "confirmed_unlocked":
        holds.append(f"translation baseline is {lock['status']}")
    if defects:
        holds.append("mechanical defects require disposition before automatic pipeline dispatch")
    if not audio or not any(item["bytes"] > 0 for item in audio):
        holds.append("local listener audio is missing or empty")
    elif not (directory / "audio.m4a").is_file() or not (directory / "audio.m4a").stat().st_size:
        holds.append("existing pipeline resume requires nonempty local audio.m4a")
    if not source_ready:
        holds.append("source provenance is missing or not a usable HTTPS/local reference")
    subjects = song.get("subjectTags", [])
    priority_reasons = []
    if any(folded(tag) == "gurbani" for tag in subjects):
        priority_reasons.append("Gurbāṇī")
    if re.search(r"\bkabir\b", folded(song.get("writer", ""))):
        priority_reasons.append("Kabīr")
    row = {"slug": slug, "title": song.get("title", ""), "priority": 0 if priority_reasons else 1,
           "priorityReasons": priority_reasons, "catalogueEntrySha256": json_digest(song),
           "readerChangedSinceCatalogueRevision": dirty, "committedReaderSha256": digest(original) if original else None,
           "counts": {"uniqueLines": len(lines), "displayOccurrences": len(sequence), "performedOccurrences": performed_count},
           "artifacts": pointers, "localAudio": audio,
           "audioHashStatus": "not hashed: inventory inspects availability only; hash before processing",
           "publishedAudio": song.get("audioSources", []), "sourceReference": source_value or None,
           "mechanicalDefects": sorted(set(defects)), "reviewNeeded": review,
           "route": "audio-first" if audio_reasons else "text-only", "audioFirstReasons": sorted(set(audio_reasons)),
           "translationLock": lock, "manifestHoldReasons": holds, "audioQualified": False}
    row["inputSha256"] = json_digest({"catalogue": song, "artifacts": pointers, "lock": lock})
    return row


def build_inventory(root: Path = ROOT, *, catalogue_ref: str = "HEAD", locks_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    revision = git(root, "rev-parse", "--verify", f"{catalogue_ref}^{{commit}}").decode().strip()
    catalogue_source = committed_bytes(root, revision, "data/songs.js")
    if catalogue_source is None:
        raise ValueError("committed catalogue is missing")
    catalogue = load_javascript(catalogue_source).get("BHAKTI_SONGS")
    if not isinstance(catalogue, list) or not catalogue:
        raise ValueError("committed catalogue must be a non-empty list")
    slugs = [row.get("slug") if isinstance(row, dict) else None for row in catalogue]
    if any(not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) for slug in slugs):
        raise ValueError("committed catalogue contains an invalid slug")
    if len(slugs) != len(set(slugs)):
        raise ValueError("committed catalogue contains duplicate slugs")
    locks_path = (locks_path or root / "data/editorial_baselines.json").resolve()
    lock_errors: list[str] = []
    registry = read_object(locks_path, lock_errors)
    if lock_errors or (registry and (registry.get("version") != 1 or not isinstance(registry.get("songs"), dict))):
        raise ValueError("invalid editorial baseline registry; refuse to lose locks")
    locks = registry.get("songs", {})
    if any(not isinstance(value, dict) or not value for value in locks.values()):
        raise ValueError("invalid editorial baseline lock entry")
    rows = sorted((inspect_song(root, revision, song, locks) for song in catalogue),
                  key=lambda row: (row["priority"], row["slug"]))
    catalogue_by_slug = {song["slug"]: song for song in catalogue}
    jobs = []
    for row in rows:
        if row["manifestHoldReasons"]:
            continue
        song = catalogue_by_slug[row["slug"]]
        audio = next(item for item in row["localAudio"] if item["path"].endswith("/audio.m4a"))
        jobs.append({"slug": row["slug"], "source": str(root / audio["path"]),
                     "title": song.get("title", ""), "writer": song.get("writer", ""),
                     "singer": song.get("singer", ""), "composer": song.get("composer", ""),
                     "languages": song.get("languageTags", []), "subjectTags": song.get("subjectTags", []),
                     "searchAliases": song.get("searchAliases", []), "reviewInputSha256": row["inputSha256"]})
    return {"schemaVersion": 1, "catalogueRevision": revision, "catalogueSha256": digest(catalogue_source),
            "locksSha256": digest(locks_path.read_bytes()) if locks_path.is_file() else None,
            "counts": {"songs": len(rows), "uniqueLines": sum(row["counts"]["uniqueLines"] for row in rows),
                       "displayOccurrences": sum(row["counts"]["displayOccurrences"] for row in rows),
                       "performedOccurrences": sum(row["counts"]["performedOccurrences"] or 0 for row in rows),
                       "unknownPerformedCounts": sum(row["counts"]["performedOccurrences"] is None for row in rows),
                       "routes": dict(sorted(Counter(row["route"] for row in rows).items())),
                       "manifestEligible": len(jobs)}, "songs": rows,
            "pipelineManifest": {"songs": jobs, "audioQualified": False,
                                 "executionGate": "OpenRouter funding and the selected model's audio qualification must be established before dispatch; preparation is not publication approval"}}


def write_inventory(root: Path, output: Path, inventory: dict[str, Any]) -> None:
    try:
        output.resolve().relative_to((root / ".transcription").resolve())
    except ValueError as exc:
        raise ValueError("output must stay in the private .transcription directory") from exc
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("inventory.json", inventory), ("audio-repair-intake.json", inventory["pipelineManifest"]),
                        ("text-review-slugs.json", {"slugs": [row["slug"] for row in inventory["songs"]
                                                              if row["route"] == "text-only"], "autoApply": False})):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue-ref", default="HEAD", help="Committed published catalogue revision; never the dirty working catalogue")
    parser.add_argument("--locks", type=Path, default=ROOT / "data/editorial_baselines.json")
    parser.add_argument("--output", type=Path, default=ROOT / ".transcription/library-review")
    options = parser.parse_args()
    inventory = build_inventory(ROOT, catalogue_ref=options.catalogue_ref, locks_path=options.locks)
    write_inventory(ROOT, options.output, inventory)
    print(json.dumps({"counts": inventory["counts"], "output": str(options.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
