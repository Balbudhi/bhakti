#!/usr/bin/env python3
"""Report whether every published reader satisfies the canonical data contract.

This does not alter song data. It makes missing source script, meta, or timing
arrays visible before a migration or release rather than allowing a mixed
legacy/new format to look standardized by accident.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import tag_taxonomy
import gloss_policy
import source_word_map
import normalize_embedded_repeats


ROOT = Path(__file__).resolve().parents[1]
VALID_SECTIONS = {"invocation", "refrain", "verse", "bridge", "closing", "spoken", "instrumental"}
REQUIRED_META = {"title", "credit", "writer", "singer", "composer", "languages", "subjectTags",
                 "timingStatus", "translationStatus", "sourceStatus"}
PRESERVED_TERMS = json.loads((ROOT / "data" / "preserved_terms.json").read_text(encoding="utf-8")).get("terms", {})


def load_data(path: Path) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    output = subprocess.run(["node", "-e", script, str(path)], check=True, text=True, capture_output=True).stdout
    return json.loads(output)


def audit_song(directory: Path, catalogue_entry: dict[str, Any] | None = None) -> dict[str, Any]:
    data_path = directory / "data.js"
    problems: list[str] = []
    if not data_path.is_file():
        return {"slug": directory.name, "status": "legacy", "problems": ["no song-local data.js"]}
    try:
        data = load_data(data_path)
    except subprocess.CalledProcessError as exc:
        return {"slug": directory.name, "status": "blocked", "problems": [f"data.js cannot execute: {exc.stderr.strip()}"]}
    required = ["SONG_META", "SONG_LINES", "SONG_SEQUENCE", "SONG_TIMINGS"]
    problems.extend(f"missing window.{key}" for key in required if key not in data)
    meta = data.get("SONG_META", {})
    if not isinstance(meta, dict):
        problems.append("SONG_META is not an object")
    else:
        problems.extend(f"SONG_META lacks {key}" for key in sorted(REQUIRED_META - set(meta)))
        if not isinstance(meta.get("languages"), list) or not meta.get("languages"):
            problems.append("SONG_META languages must be a non-empty list")
        if not isinstance(meta.get("subjectTags"), list):
            problems.append("SONG_META subjectTags must be a list")
        for role in ("writer", "singer", "composer"):
            if not isinstance(meta.get(role), str):
                problems.append(f"SONG_META {role} must be a string")
        if meta.get("timingStatus") != "start-only-reviewed":
            problems.append("SONG_META timingStatus is not start-only-reviewed")
    lines = data.get("SONG_LINES", {})
    if not isinstance(lines, dict):
        problems.append("SONG_LINES is not an object")
        lines = {}
    inferred_tags = tag_taxonomy.infer_named_subject_tags(lines.values())
    if isinstance(meta, dict):
        for tag in inferred_tags:
            if tag not in meta.get("subjectTags", []):
                problems.append(f"SONG_META subjectTags omit explicit lyric name {tag}")
        if catalogue_entry is not None:
            if meta.get("languages") != catalogue_entry.get("languageTags"):
                problems.append("catalogue languageTags differ from SONG_META languages")
            if meta.get("subjectTags") != catalogue_entry.get("subjectTags"):
                problems.append("catalogue subjectTags differ from SONG_META subjectTags")
    sequence, timing = data.get("SONG_SEQUENCE", []), data.get("SONG_TIMINGS", [])
    instrumental_refs = {entry.get("ref") for entry in sequence if isinstance(entry, dict) and entry.get("section") == "instrumental"}
    for line_id, line in lines.items():
        if not isinstance(line, dict):
            problems.append(f"{line_id} is not a line object")
            continue
        if line_id not in instrumental_refs and not str(line.get("source", "")).strip():
            problems.append(f"{line_id} lacks source script")
        if not str(line.get("roman", "")).strip():
            problems.append(f"{line_id} lacks IAST")
        if not str(line.get("english", "")).strip():
            problems.append(f"{line_id} lacks literal English")
        fictional = gloss_policy.fictional_coinages(line.get("english", ""))
        if fictional:
            problems.append(f"{line_id} English uses fictional coinage {fictional}")
        if not isinstance(line.get("words"), list) or not line["words"]:
            problems.append(f"{line_id} lacks word glosses")
        else:
            repeated_phrase_count = normalize_embedded_repeats.repeat_factor(line["words"])
            if repeated_phrase_count > 1:
                problems.append(
                    f"{line_id} embeds an exact {repeated_phrase_count}× repeated phrase instead of using sequence repeats"
                )
            if line_id not in instrumental_refs:
                problems.extend(
                    f"{line_id} {problem}"
                    for problem in source_word_map.validate_source_words(
                        str(line.get("source") or ""), line["words"], line.get("sourceWords")
                    )
                )
            roman = str(line.get("roman", ""))
            cursor = 0
            for word_index, word in enumerate(line["words"]):
                token = str(word.get("roman", "")) if isinstance(word, dict) else ""
                gloss = str(word.get("gloss", "")) if isinstance(word, dict) else ""
                at = roman.casefold().find(token.casefold(), cursor) if token else -1
                if at < 0 or not gloss.strip():
                    problems.append(f"{line_id} word[{word_index}] cannot map to roman text or lacks a gloss")
                    break
                if gloss_policy.is_self_referential(token, gloss):
                    problems.append(f"{line_id} word[{word_index}] gloss repeats the visible term instead of explaining it")
                if gloss_policy.is_placeholder_gloss(gloss):
                    problems.append(f"{line_id} word[{word_index}] gloss is a placeholder rather than an explanation")
                fictional = gloss_policy.fictional_coinages(gloss)
                if fictional:
                    problems.append(f"{line_id} word[{word_index}] gloss uses fictional coinage {fictional}")
                cursor = at + len(token)
                concept_key = word.get("concept_key") if isinstance(word, dict) else None
                preserve = word.get("preserve_in_english") if isinstance(word, dict) else False
                if concept_key and concept_key not in PRESERVED_TERMS:
                    problems.append(f"{line_id} word[{word_index}] uses unknown preserved concept {concept_key!r}")
                if preserve:
                    canonical = str(PRESERVED_TERMS.get(concept_key, {}).get("iast", ""))
                    plain_english = re.sub(r"\{[^:{}]*:([^{}]*)\}", r"\1", str(line.get("english", "")))
                    if not canonical or canonical.casefold() not in plain_english.casefold():
                        problems.append(f"{line_id} word[{word_index}] does not preserve {canonical or concept_key} in English")
            linked_indices: set[int] = set()
            for marker in re.finditer(r"\{([^:}]+):([^}]*)\}", str(line.get("english", ""))):
                try:
                    indices = [int(value.strip()) for value in marker.group(1).split(",")]
                except ValueError:
                    problems.append(f"{line_id} has malformed English word linkage")
                    break
                if any(index < 0 or index >= len(line["words"]) for index in indices):
                    problems.append(f"{line_id} English linkage references an invalid word index")
                    break
                linked_indices.update(indices)
            missing_indices = sorted(set(range(len(line["words"]))) - linked_indices)
            if missing_indices:
                problems.append(f"{line_id} English linkage omits word indices {missing_indices}")
    if not isinstance(sequence, list) or not isinstance(timing, list) or len(sequence) != len(timing):
        problems.append("sequence/timing arrays are missing or differ in length")
    if isinstance(sequence, list):
        notices = meta.get("sectionNotices", []) if isinstance(meta, dict) else []
        if not isinstance(notices, list):
            problems.append("SONG_META sectionNotices must be a list when present")
        else:
            notice_indices = []
            for notice_index, notice in enumerate(notices):
                if (not isinstance(notice, dict) or not isinstance(notice.get("sequenceIndex"), int)
                        or not 0 <= notice["sequenceIndex"] < len(sequence)
                        or not str(notice.get("title", "")).strip()
                        or not isinstance(notice.get("poet", ""), str)
                        or not isinstance(notice.get("note", ""), str)):
                    problems.append(f"SONG_META sectionNotices[{notice_index}] is invalid")
                    continue
                notice_indices.append(notice["sequenceIndex"])
            if len(notice_indices) != len(set(notice_indices)):
                problems.append("SONG_META sectionNotices repeat a sequence index")
        adapted_indices = meta.get("adaptedSequenceIndices", []) if isinstance(meta, dict) else []
        if (not isinstance(adapted_indices, list)
                or any(not isinstance(index, int) or not 0 <= index < len(sequence) for index in adapted_indices)):
            problems.append("SONG_META adaptedSequenceIndices contains an invalid sequence index")
        previous_start = -0.001
        for index, entry in enumerate(sequence):
            if not isinstance(entry, dict) or entry.get("section") not in VALID_SECTIONS:
                problems.append(f"sequence[{index}] lacks a canonical section")
                continue
            if entry.get("ref") not in lines:
                problems.append(f"sequence[{index}] references unknown line {entry.get('ref')!r}")
            if "repeats" not in entry:
                problems.append(f"sequence[{index}] lacks repeats")
            try:
                repeats = int(entry.get("repeats", 1) or 1)
                if repeats < 1:
                    raise ValueError
            except (TypeError, ValueError):
                problems.append(f"sequence[{index}] has an invalid repeats value")
            if index and entry.get("ref") == sequence[index - 1].get("ref") and entry.get("section") == sequence[index - 1].get("section"):
                problems.append(f"sequence[{index - 1}] and sequence[{index}] should be one repeated block")
            if index < len(timing):
                point = timing[index]
                try:
                    start, end = float(point["start"]), float(point["end"])
                    if start < 0 or end < start or start + 0.01 < previous_start:
                        raise ValueError
                    previous_start = start
                except (KeyError, TypeError, ValueError):
                    problems.append(f"timing[{index}] is invalid or out of order")
    return {"slug": directory.name, "status": "ready" if not problems else "migration-needed", "problems": problems}


def main() -> int:
    catalogue = load_data(ROOT / "data" / "songs.js").get("BHAKTI_SONGS", [])
    by_slug = {entry.get("slug"): entry for entry in catalogue if isinstance(entry, dict)}
    reports = [audit_song(directory, by_slug.get(directory.name))
               for directory in sorted((ROOT / "songs").iterdir()) if directory.is_dir()]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report["status"] == "ready" for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
