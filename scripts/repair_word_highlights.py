#!/usr/bin/env python3
"""Repair word-to-English highlight spans without changing approved wording."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import bhakti_pipeline as pipeline
import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = 1


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slugs, or 'all'.")
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--emit-patch", action="store_true")
    return parser.parse_args()


def load_reader(slug: str) -> dict[str, Any]:
    path = ROOT / "songs" / slug / "data.js"
    script = """const fs=require('fs'),vm=require('vm');const c={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),c,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(c.window));"""
    return json.loads(subprocess.run(
        ["node", "-e", script, str(path)], check=True, capture_output=True, text=True
    ).stdout)


def plain(value: str) -> str:
    return re.sub(r"\{[^:{}]*:([^{}]*)\}", r"\1", value)


def mapping_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"mappings": {"type": "array", "items": {
        "type": "object", "properties": {
            "uid": {"type": "string"},
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "word_indices": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "word_indices"], "additionalProperties": False}},
            "notes": {"type": "string"}},
        "required": ["uid", "segments", "notes"], "additionalProperties": False}}},
        "required": ["mappings"], "additionalProperties": False}


def review_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "properties": {
            "uid": {"type": "string"}, "passes": {"type": "boolean"},
            "incorrect_segment_indices": {"type": "array", "items": {"type": "integer"}},
            "missing_word_indices": {"type": "array", "items": {"type": "integer"}},
            "reason": {"type": "string"}},
        "required": ["uid", "passes", "incorrect_segment_indices", "missing_word_indices", "reason"],
        "additionalProperties": False}}}, "required": ["reviews"], "additionalProperties": False}


def validate(records: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> list[str]:
    expected = [record["uid"] for record in records]
    observed = [mapping.get("uid") for mapping in mappings]
    errors = [] if observed == expected else [f"mapping IDs differ: expected {expected}, got {observed}"]
    by_uid = {record["uid"]: record for record in records}
    for mapping in mappings:
        record = by_uid.get(mapping.get("uid"))
        if not record:
            continue
        word_count = len(record["words"])
        covered = set()
        for segment in mapping.get("segments", []):
            for index in segment.get("word_indices", []):
                if not isinstance(index, int) or not 0 <= index < word_count:
                    errors.append(f"{mapping['uid']} has invalid word index {index!r}")
                else:
                    covered.add(index)
        rendered = plain(pipeline.segment_english(mapping.get("segments", []), ""))
        if rendered != record["english"]:
            errors.append(f"{mapping['uid']} segments do not reproduce approved English exactly")
        if covered != set(range(word_count)):
            errors.append(f"{mapping['uid']} does not cover every source word: {sorted(set(range(word_count)) - covered)}")
    return errors


def mapping_prompt(records: list[dict[str, Any]]) -> str:
    return f"""Map approved English wording to its exact source-word indices. This is alignment only: do not translate, rewrite, correct, modernize, capitalize, or repunctuate the English.

For each record, split `english` into contiguous segments that concatenate byte-for-byte to the same string. Attach every semantic segment to all source word indices that support it. Every source word index must appear in at least one segment. A single English segment may use multiple source indices; a source index may support multiple English segments. Articles, supplied pronouns, copulas, punctuation, and other genuinely inserted English function text may use an empty list, but never hide a source word by leaving its index uncovered. Account for particles, postpositions, tense/aspect, negation, modality, honorifics, and cross-line ellipsis by mapping them to the English phrase they help create.

Do not trust the old brace annotations; they are the bug being repaired. Use only source text, Romanization, indexed glosses, grammar note, and the locked plain English. Return every UID once in order. Strict JSON only.

RECORDS:
{json.dumps(records, ensure_ascii=False)}"""


def review_prompt(records: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> str:
    evidence = [{"record": record, "mapping": mapping} for record, mapping in zip(records, mappings)]
    return f"""Independently audit word-to-English highlight mappings. Do not rewrite English and do not propose stylistic changes.

For each segment, verify that every attached source index actually supports that English text according to the source, Romanization, gloss, grammar, particles, and ellipsis. Verify that no source word index is missing. Empty-index segments are allowed only for genuinely inserted English function words or punctuation. Set passes=false for a semantically wrong attachment even when numeric coverage is complete. Return every UID once in order. Strict JSON only.

EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)}"""


def records_for(slugs: list[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    readers = {slug: load_reader(slug) for slug in slugs}
    records = []
    for slug in slugs:
        for line_id, line in readers[slug].get("SONG_LINES", {}).items():
            records.append({"uid": f"{slug}::{line_id}", "slug": slug, "line_id": line_id,
                            "source": line.get("source", ""), "roman": line.get("roman", ""),
                            "words": [{"index": index, "roman": word.get("roman", ""), "gloss": word.get("gloss", "")}
                                      for index, word in enumerate(line.get("words", []))],
                            "grammar_note": line.get("grammarNote", ""),
                            "english": plain(str(line.get("english", "")))})
    return records, readers


def main() -> int:
    options = arguments()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
    records, readers = records_for(slugs)
    batches = [records[index:index + options.batch_size] for index in range(0, len(records), options.batch_size)]
    cache_dir = ROOT / ".transcription" / "word-highlight-repair"
    cache_dir.mkdir(parents=True, exist_ok=True)

    def run(index: int) -> dict[str, Any]:
        batch = batches[index]
        fingerprint = hashlib.sha256(json.dumps(
            {"version": CONTRACT_VERSION, "model": options.model, "records": batch},
            ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest()
        path = cache_dir / f"batch-{index:03d}.json"
        cached = pipeline.read_packet(path)
        if (cached and cached.get("fingerprint") == fingerprint and not options.force
                and not cached.get("validation_errors")):
            return cached
        draft = gemini.call(options.model, gemini.key(), mapping_prompt(batch), audio=None, timeout=options.timeout,
                            response_schema=mapping_schema(), schema_name="bhakti_word_highlight_mapping",
                            reasoning_effort="high", max_completion_tokens=32768)
        mappings = draft["packet"].get("mappings", [])
        errors = validate(batch, mappings)
        review = None
        if not errors:
            review = gemini.call(options.model, gemini.key(), review_prompt(batch, mappings), audio=None,
                                 timeout=options.timeout, response_schema=review_schema(),
                                 schema_name="bhakti_word_highlight_review", reasoning_effort="high",
                                 max_completion_tokens=16384)
            reviews = review["packet"].get("reviews", [])
            if [row.get("uid") for row in reviews] != [record["uid"] for record in batch]:
                errors.append("independent review IDs differ from batch")
            for row in reviews:
                if not row.get("passes") or row.get("incorrect_segment_indices") or row.get("missing_word_indices"):
                    errors.append(f"{row.get('uid')} failed independent mapping review: {row.get('reason')}")
        result = {"fingerprint": fingerprint, "records": batch, "draft": draft, "review": review,
                  "validation_errors": errors}
        pipeline.write_json(path, result)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        packets = list(pool.map(run, range(len(batches))))
    errors = [error for packet in packets for error in packet["validation_errors"]]
    mappings = [mapping for packet in packets for mapping in packet["draft"]["packet"].get("mappings", [])]
    mapping_by_uid = {mapping["uid"]: mapping for mapping in mappings}
    summary = {"songs": slugs, "lines": len(records), "errors": errors,
               "reported_cost": pipeline.reported_cost(packets)}
    if options.emit_patch and not errors:
        print("*** Begin Patch")
        for slug in slugs:
            hunks = []
            for line_id, line in readers[slug].get("SONG_LINES", {}).items():
                mapping = mapping_by_uid[f"{slug}::{line_id}"]
                new = pipeline.segment_english(mapping["segments"], plain(str(line.get("english", ""))))
                if new != line.get("english", ""):
                    hunks.append((line["roman"], line["english"], new))
            if hunks:
                print(f"*** Update File: {ROOT / 'songs' / slug / 'data.js'}")
                for roman, old, new in hunks:
                    print("@@")
                    print('     "roman": ' + json.dumps(roman, ensure_ascii=False) + ',')
                    print('-    "english": ' + json.dumps(old, ensure_ascii=False) + ',')
                    print('+    "english": ' + json.dumps(new, ensure_ascii=False) + ',')
        print("*** End Patch")
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
