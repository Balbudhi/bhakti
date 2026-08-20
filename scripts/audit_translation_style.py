#!/usr/bin/env python3
"""Audit public English against reviewed word glosses without touching audio."""

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
PROMPT_VERSION = 2


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slugs, or 'all'.")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def load_reader(slug: str) -> dict[str, Any]:
    path = ROOT / "songs" / slug / "data.js"
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    return json.loads(subprocess.run(
        ["node", "-e", script, str(path)], check=True, capture_output=True, text=True
    ).stdout)


def plain_english(value: str) -> str:
    return re.sub(r"\{[^:{}]*:([^{}]*)\}", r"\1", value)


def response_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"},
            "revised_english": {"type": "string"},
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "word_indices": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "word_indices"], "additionalProperties": False}},
            "change_needed": {"type": "boolean"},
            "issue_type": {"type": "string"},
            "reason": {"type": "string"},
            "uncertainty": {"type": "string"},
        }, "required": ["id", "revised_english", "segments", "change_needed", "issue_type", "reason", "uncertainty"],
        "additionalProperties": False}},
    }, "required": ["reviews"], "additionalProperties": False}


def record(line_id: str, line: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": line_id,
        "source_text": line.get("source", ""),
        "roman": line.get("roman", ""),
        "current_english": plain_english(str(line.get("english", ""))),
        "word_glosses": [{"index": index, "roman": word.get("roman", ""), "gloss": word.get("gloss", "")}
                         for index, word in enumerate(line.get("words", []))],
        "grammar_note": line.get("grammarNote", ""),
    }


def prompt(slug: str, targets: list[dict[str, Any]], context: list[dict[str, Any]]) -> str:
    return f"""You are the final English editor for a devotional-song reader. Audit every TARGET line against its source, Romanization, reviewed word glosses, and grammar note. The gloss record is the semantic constraint and must be considered before writing the sentence.

The current English may be a deliberate human translation. Literal strangeness, repetition, personification, unusual agency, and concrete ritual or bodily imagery can be essential poetry; conventional English is not automatically better. Preserve supported expressions such as “my breath will abandon me,” “from the inside,” or a deity resting in the speaker's palm even when a smoother idiom exists. Correct a line only for a demonstrable meaning error, grammatical failure, unsupported addition, or wording that truly obstructs understanding. “Cast a glance of mercy” may become “look upon me with mercy,” but do not generalize that decision into permission to replace other literal images. Preserve an alms bag, garment hem, lotus, dust, ocean, threshold, cage, and other concrete source images. Do not introduce or change theology, sentiment, agency, tense, pronouns, causal links, or metaphor.

If the current line is faithful and intelligible, retain it exactly and set change_needed=false. Awkwardness alone is insufficient when it arises from a meaningful literal image or poetic choice. Explain the precise lexical or grammatical evidence for every proposed change; personal synonym preference is never enough.

For every line, return a complete revised sentence plus ordered display segments. Segment text must concatenate, with ordinary spacing and punctuation, to revised_english. Each semantic segment must reference the exact supporting word indices. Punctuation or necessary English function words may use an empty index list. Mark real source ambiguity rather than guessing.

Song: {slug}

TARGETS (return these IDs only, in this order):
{json.dumps(targets, ensure_ascii=False)}

NEARBY CONTEXT (do not return these IDs unless they are also targets):
{json.dumps(context, ensure_ascii=False)}

Return strict JSON only."""


def validate(targets: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[str]:
    expected = [target["id"] for target in targets]
    observed = [review.get("id") for review in reviews]
    errors = [] if observed == expected else [f"IDs differ: expected {expected}, got {observed}"]
    words = {target["id"]: len(target["word_glosses"]) for target in targets}
    for review in reviews:
        for segment in review.get("segments", []):
            for index in segment.get("word_indices", []):
                if not isinstance(index, int) or not 0 <= index < words.get(review.get("id"), 0):
                    errors.append(f"{review.get('id')} has invalid word index {index!r}")
        rendered = plain_english(pipeline.segment_english(review.get("segments", []), "")).strip()
        expected_text = str(review.get("revised_english", "")).strip()
        if re.sub(r"\s+", " ", rendered) != re.sub(r"\s+", " ", expected_text):
            errors.append(f"{review.get('id')} segments do not reconstruct revised_english")
    return errors


def run_slug(slug: str, options: argparse.Namespace) -> dict[str, Any]:
    reader = load_reader(slug)
    records = [record(line_id, line) for line_id, line in reader.get("SONG_LINES", {}).items()]
    if not records:
        raise RuntimeError(f"{slug} has no lines")
    batches = [records[index:index + options.batch_size] for index in range(0, len(records), options.batch_size)]
    review_dir = ROOT / "songs" / slug / ".transcription" / "translation-style-audit"
    review_dir.mkdir(parents=True, exist_ok=True)

    def run_batch(index: int) -> dict[str, Any]:
        targets = batches[index]
        start = index * options.batch_size
        context = records[max(0, start - 2):start] + records[start + len(targets):start + len(targets) + 2]
        fingerprint = hashlib.sha256(json.dumps(
            {"version": PROMPT_VERSION, "model": options.model, "targets": targets, "context": context},
            ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest()
        path = review_dir / f"batch-{index:03d}.json"
        cached = pipeline.read_packet(path)
        if cached and cached.get("fingerprint") == fingerprint and not options.force:
            cached_errors = validate(targets, cached.get("response", {}).get("packet", {}).get("reviews", []))
            cached["validation_errors"] = cached_errors
            pipeline.write_json(path, cached)
            if not cached_errors:
                return cached
        response = gemini.call(
            options.model, gemini.key(), prompt(slug, targets, context), audio=None, timeout=options.timeout,
            response_schema=response_schema(), schema_name="bhakti_translation_style_audit",
            reasoning_effort="high", max_completion_tokens=32768,
        )
        errors = validate(targets, response["packet"].get("reviews", []))
        result = {"fingerprint": fingerprint, "target_ids": [target["id"] for target in targets],
                  "response": response, "validation_errors": errors}
        pipeline.write_json(path, result)
        if errors:
            raise RuntimeError(f"{slug} batch {index} failed validation: {errors[:3]}")
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(batches))) as pool:
        packets = list(pool.map(run_batch, range(len(batches))))
    reviews = [review for packet in packets for review in packet["response"]["packet"]["reviews"]]
    changes = [review for review in reviews if review.get("change_needed")]
    report = {"slug": slug, "model": options.model, "prompt_version": PROMPT_VERSION,
              "line_count": len(records), "change_count": len(changes), "reviews": reviews,
              "reported_openrouter_cost": pipeline.reported_cost(packets)}
    pipeline.write_json(review_dir / "review.json", report)
    return {"slug": slug, "lines": len(records), "changes": len(changes),
            "cost": report["reported_openrouter_cost"]}


def main() -> int:
    options = arguments()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        futures = {pool.submit(run_slug, slug, options): slug for slug in slugs}
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"slug": futures[future], "error": str(exc)})
    results.sort(key=lambda item: item["slug"])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any("error" in result for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
