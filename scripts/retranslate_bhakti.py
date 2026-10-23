#!/usr/bin/env python3
"""Create gloss-first translation review packets for existing Bhakti readers.

This is intentionally text-only: it does not redownload, retranscribe, or
retime audio. It first rebuilds word glosses, then asks Gemini to derive a
literal English line solely from that gloss record through the production
translation and independent-review stages, then compares the published wording.
Public data is not overwritten by this command.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import process_song_gemini as gemini
import bhakti_pipeline as pipeline
import editorial_baselines
import bhakti_translation_policy as translation_policy


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slug(s), or 'all'")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--lexical-support", type=Path, help="Private witnessed lexical support packet")
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--reuse-glosses", action="store_true",
                        help="Reuse a matching validated shared gloss cache; rerun English and independent review.")
    return parser.parse_args()


def load_reader(slug: str, source: bytes | None = None) -> dict[str, Any]:
    if not slug or Path(slug).name != slug or slug in {".", ".."}:
        raise RuntimeError("invalid song slug")
    data = ROOT / "songs" / slug / "data.js"
    if not data.is_file():
        raise RuntimeError(f"missing data.js for {slug}")
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(0,'utf8'),ctx,{filename:process.argv[1],timeout:1000});
process.stdout.write(JSON.stringify(ctx.window));"""
    output = subprocess.run(["node", "-e", script, str(data)], check=True,
                            input=source if source is not None else data.read_bytes(), capture_output=True).stdout
    reader = json.loads(output)
    if not isinstance(reader.get("SONG_LINES"), dict) or not reader["SONG_LINES"]:
        raise RuntimeError(f"{slug} has no SONG_LINES")
    return reader


def source_lines(reader: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep existing display tokens/links; carry every performed local context.

    This is a text repair input, not a new claim that audio was independently
    audited. A different token division needs a separate source-map repair.
    """
    lines = reader["SONG_LINES"]
    sequence = reader.get("SONG_SEQUENCE")
    if not isinstance(sequence, list) or not sequence:
        raise RuntimeError("reader lacks performed sequence")
    if any(not isinstance(event, dict) or event.get("ref") not in lines for event in sequence):
        raise RuntimeError("performed sequence refers to a missing line")
    ordered = list(dict.fromkeys(event["ref"] for event in sequence))
    if set(ordered) != set(lines):
        raise RuntimeError("reader has lines outside performed sequence")
    for line_id, line in lines.items():
        if not isinstance(line, dict) or not line.get("source") or not line.get("roman"):
            raise RuntimeError(f"{line_id}: missing source or roman")
        words = line.get("words", [])
        if not isinstance(words, list) or any(not isinstance(word, dict) for word in words):
            raise RuntimeError(f"{line_id}: invalid word map")
        try:
            translation_policy.word_tokens(line)
        except ValueError as exc:
            raise RuntimeError(f"{line_id}: existing word map requires token reconstruction: {exc}") from exc
        errors = pipeline.source_word_map.validate_source_words(line["source"], words, line.get("sourceWords"))
        if errors:
            raise RuntimeError(f"{line_id}: existing word map invalid: " + "; ".join(errors))
    performed = [{"id": event["ref"], "source_text": lines[event["ref"]]["source"],
                  "roman": lines[event["ref"]]["roman"]} for event in sequence]
    contexts: dict[str, list[dict[str, Any]]] = {line_id: [] for line_id in ordered}
    for index, event in enumerate(sequence):
        context = {"before": performed[max(0, index - 2):index], "after": performed[index + 1:index + 3]}
        if context not in contexts[event["ref"]]:
            contexts[event["ref"]].append(context)
    return [{"id": line_id, "source_text": lines[line_id]["source"], "roman": lines[line_id]["roman"],
             "kind": next(event.get("section", "verse") for event in sequence if event["ref"] == line_id),
             "performed_context": contexts[line_id], "sourceWords": lines[line_id]["sourceWords"],
             "lexical_tokens": translation_policy.word_tokens(lines[line_id]),
             **({"sourceLanguage": lines[line_id]["sourceLanguage"]} if "sourceLanguage" in lines[line_id] else {})}
            for line_id in ordered]


def supplied_baseline(slug: str, reader: dict[str, Any]) -> Any:
    baseline = editorial_baselines.load_baselines(ROOT).get(slug)
    if baseline:
        expected = baseline["plainEnglishByLine"]
        if set(expected) != set(reader["SONG_LINES"]):
            raise RuntimeError(f"{slug}: protected English line population changed")
        return expected
    private = ROOT / "songs" / slug / ".transcription"
    source = pipeline.read_packet(private / "source.json") or {}
    summary = pipeline.read_packet(private / "pipeline" / "song-packet.json") or {}
    values = [obj[field] for obj in (reader.get("SONG_META", {}), source, summary, summary.get("job", {}))
              if isinstance(obj, dict)
              for field in ("humanTranslation", "human_translation", "providedTranslation", "provided_translation")
              if obj.get(field) not in (None, "", False, "(none supplied)")]
    if not values:
        return None
    resolved = []
    for value in values:
        if not isinstance(value, (str, dict)) or isinstance(value, bool):
            raise RuntimeError("stored human translation declaration has no recoverable wording")
        if isinstance(value, str):
            try:
                path = Path(value).expanduser()
                if path.is_file():
                    value = path.read_text(encoding="utf-8")
            except OSError:
                # A full poem is literal content, not necessarily a valid path.
                pass
        if value not in resolved:
            resolved.append(value)
    if len(resolved) != 1:
        raise RuntimeError("conflicting stored human translation declarations")
    value = resolved[0]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            value = parsed
        else:
            ordered = list(dict.fromkeys(event["ref"] for event in reader["SONG_SEQUENCE"]))
            texts = [line for line in value.splitlines() if line.strip()]
            if len(texts) != len(ordered):
                raise RuntimeError("stored supplied English needs an exact line-ID mapping before reconstruction")
            value = dict(zip(ordered, texts))
    if (set(value) != set(reader["SONG_LINES"])
            or any(not isinstance(text, str) or not text.strip() for text in value.values())):
        raise RuntimeError("stored supplied English line population or wording is invalid")
    return value


def atomic_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".review-", suffix=".json", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run_slug(slug: str, options: argparse.Namespace) -> dict[str, Any]:
    if not slug or Path(slug).name != slug or slug in {".", ".."}:
        raise RuntimeError("invalid song slug")
    review_dir = ROOT / "songs" / slug / ".transcription" / "translation-review-gloss-first"
    report_path = review_dir / "review.json"
    # Invalidate any previous successful report before validation or paid work.
    # Stage caches remain independently reusable only through shared contracts.
    identity = None
    atomic_report(report_path, {"slug": slug, "status": "in-progress", "reader_sha256": identity})
    try:
        public_bytes = (ROOT / "songs" / slug / "data.js").read_bytes()
        identity = hashlib.sha256(public_bytes).hexdigest()
        reader = load_reader(slug, public_bytes)
        canonical = source_lines(reader)
        baseline = supplied_baseline(slug, reader)
        languages = reader.get("SONG_META", {}).get("languages", [])
        audited = {"packet": {"verified_lines": canonical, "metadata": {"languages": languages}}}
        job = {"slug": slug, "languages": languages}
        workspace = review_dir / "shared-text-stages"
        if baseline is not None:
            # Pass a real file so the shared resolver never treats a long poem
            # or JSON line map as an operating-system filename.
            baseline_path = review_dir / "supplied-english.txt"
            baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
            job["providedTranslation"] = str(baseline_path)
        gloss_options = argparse.Namespace(**vars(options), force=not options.reuse_glosses)
        gloss_options.source_slug = slug
        glosses = pipeline.gloss(workspace, audited, gloss_options)
        # The documented option reuses glosses only; English and its independent
        # review run again, using the shared policy/evidence fingerprints.
        translation_options = argparse.Namespace(**vars(options), force=True)
        translation_options.source_slug = slug
        translations = pipeline.translate(workspace, audited, glosses, job, translation_options)
        gloss_by_id = {row["id"]: row for row in glosses["packet"]["glosses"]}
        english_by_id = {row["id"]: row for row in translations["packet"]["translations"]}
        candidate = copy.deepcopy(reader)
        comparison = []
        for source in canonical:
            line_id = source["id"]
            line = candidate["SONG_LINES"][line_id]
            gloss = gloss_by_id[line_id]
            translation = english_by_id[line_id]
            line["words"] = copy.deepcopy(gloss["word_glosses"])
            line["grammarNote"] = gloss.get("grammar_note", "")
            line["english"] = pipeline.segment_english(translation["segments"], translation["literal_english"])
            proposed = editorial_baselines.plain_english(line["english"])
            if baseline is not None and baseline.get(line_id) != proposed:
                raise RuntimeError(f"{slug}:{line_id}: owner-designated English changed")
            published = editorial_baselines.plain_english(reader["SONG_LINES"][line_id]["english"])
            comparison.append({"id": line_id, "published": published, "proposed": proposed,
                               "changed": published != proposed})
        editorial_baselines.assert_english_preserved(slug, candidate["SONG_LINES"], root=ROOT)
        if (ROOT / "songs" / slug / "data.js").read_bytes() != public_bytes:
            raise RuntimeError("reader changed during review; rerun against current content")
        report = {"slug": slug, "status": "review-required", "reader_sha256": identity,
                  "model_requested": options.model, "source_lines": canonical,
                  "glosses": glosses, "translations": translations, "comparison": comparison,
                  "candidate_reader": candidate,
                  "gloss_cache_reuse_requested": bool(options.reuse_glosses),
                  "artifact_reported_openrouter_cost": pipeline.reported_cost(glosses, translations)}
        atomic_report(report_path, report)
        return {"slug": slug, "status": report["status"],
                "artifact_reported_openrouter_cost": report["artifact_reported_openrouter_cost"]}
    except Exception as exc:
        atomic_report(report_path, {"slug": slug, "status": "blocked", "reader_sha256": identity,
                                    "error": str(exc)})
        raise


def main() -> int:
    options = parse_args()
    slugs = (sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir())
             if options.songs == ["all"] else list(dict.fromkeys(options.songs)))
    def guarded(slug: str) -> dict[str, Any]:
        try:
            return run_slug(slug, options)
        except Exception as exc:
            # One legacy reader must not prevent independent readers from
            # receiving their requested text-only review packet.
            return {"slug": slug, "status": "blocked", "error": str(exc)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        results = list(pool.map(guarded, slugs))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(result["status"] == "blocked" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
