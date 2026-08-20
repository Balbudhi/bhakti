#!/usr/bin/env python3
"""Review and optionally apply native source script for legacy romanized lines.

This is text-only. Gemini transliterates the existing reviewed romanization;
it may not rewrite, translate, add, or omit a word. Application is blocked by
missing IDs, uncertainty, low round-trip similarity, or the wrong Unicode
script block.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_RANGES = {
    "Devanagari": (0x0900, 0x097F),
    "Gurmukhi": (0x0A00, 0x0A7F),
    "Kannada": (0x0C80, 0x0CFF),
}
LANGUAGE_SCRIPT = {"Hindi": "Devanagari", "Sanskrit": "Devanagari", "Punjabi": "Gurmukhi", "Kannada": "Kannada"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-existing", action="store_true",
                        help="Apply an already-reviewed private artifact without another API call.")
    return parser.parse_args()


def load_js(path: Path) -> dict[str, Any]:
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window));"""
    return json.loads(subprocess.run(["node", "-e", script, str(path)], check=True, capture_output=True, text=True).stdout)


def comparable(text: str) -> str:
    value = unicodedata.normalize("NFD", text).casefold()
    return "".join(char for char in value if char.isalnum() and not unicodedata.combining(char))


def script_ratio(text: str, script: str) -> float:
    low, high = SCRIPT_RANGES[script]
    letters = [char for char in text if char.isalpha()]
    return sum(low <= ord(char) <= high for char in letters) / len(letters) if letters else 0.0


def has_uncertainty(value: Any) -> bool:
    return str(value or "").strip().casefold() not in {"", "none", "no", "null", "n/a"}


def validate_rows(lines: list[dict[str, Any]], rows: list[dict[str, Any]], scripts: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    by_id = {row.get("id"): row for row in rows}
    errors: list[str] = []
    expected = {line["id"] for line in lines}
    if set(by_id) != expected:
        errors.append("returned line IDs do not exactly match requested IDs")
    for line in lines:
        row = by_id.get(line["id"], {})
        script = row.get("script")
        similarity = difflib.SequenceMatcher(None, comparable(line["roman"]), comparable(str(row.get("roman_roundtrip", "")))).ratio()
        row["roundtrip_similarity"] = round(similarity, 3)
        if has_uncertainty(row.get("uncertainty")):
            errors.append(f"{line['id']} has uncertainty")
        if script not in scripts or script_ratio(str(row.get("source_text", "")), str(script)) < 0.7:
            errors.append(f"{line['id']} has wrong or insufficient native script")
        if similarity < 0.82:
            errors.append(f"{line['id']} round-trip similarity is {similarity:.3f}")
    return by_id, errors


def write_data(path: Path, data: dict[str, Any]) -> None:
    content = ("window.SONG_META = " + json.dumps(data["SONG_META"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_LINES = " + json.dumps(data["SONG_LINES"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_SEQUENCE = " + json.dumps(data["SONG_SEQUENCE"], ensure_ascii=False, indent=2) + ";\n\n" +
               "window.SONG_TIMINGS = " + json.dumps(data["SONG_TIMINGS"], ensure_ascii=False, indent=2) + ";\n")
    path.write_text(content, encoding="utf-8")


def review(slug: str, options: argparse.Namespace) -> dict[str, Any]:
    song = ROOT / "songs" / slug
    path = song / "data.js"
    data = load_js(path)
    languages = data["SONG_META"].get("languages", [])
    scripts = sorted({LANGUAGE_SCRIPT[language] for language in languages if language in LANGUAGE_SCRIPT})
    if not scripts:
        raise RuntimeError("no supported native script for declared languages")
    instrumental = {entry["ref"] for entry in data["SONG_SEQUENCE"] if entry.get("section") == "instrumental"}
    lines = [{"id": line_id, "roman": line.get("roman", ""), "word_units": line.get("words", [])}
             for line_id, line in data["SONG_LINES"].items() if not line.get("source") and line_id not in instrumental]
    if not lines:
        return {"slug": slug, "status": "nothing-to-review", "cost": 0.0}
    target = song / ".transcription" / "source-script-review.json"
    if options.apply_existing:
        if not target.is_file():
            raise RuntimeError("no existing source-script review artifact")
        artifact = json.loads(target.read_text(encoding="utf-8"))
        rows = artifact["result"]["packet"]["lines"]
        by_id, errors = validate_rows(lines, rows, scripts)
        if errors:
            return {"slug": slug, "status": "blocked", "cost": 0.0, "errors": errors}
        language = languages[0] if languages else ""
        for line in lines:
            line_id = line["id"]
            data["SONG_LINES"][line_id]["source"] = by_id[line_id]["source_text"]
            data["SONG_LINES"][line_id]["sourceLanguage"] = {"Hindi": "hi", "Sanskrit": "sa", "Punjabi": "pa", "Kannada": "kn"}.get(language, "")
        data["SONG_META"]["sourceStatus"] = "reviewed"
        write_data(path, data)
        return {"slug": slug, "status": "applied", "cost": 0.0, "errors": []}
    prompt = f"""Transliterate these already-reviewed devotional lyric lines into their native source script. This is transcription between scripts, not translation or lyric correction.

Allowed native scripts: {', '.join(scripts)}. Preserve every word, repetition, vocative, particle, punctuation boundary, and meaningful unit. Do not modernize, translate, add, remove, or silently correct the romanized text. Use the word-unit glosses only to disambiguate spelling. Independently romanize your resulting source_text back into `roman_roundtrip`; do not copy the supplied roman string into that field. Before returning, compare that round trip with the supplied romanization and correct any dropped consonant, vowel, nasal, or grammatical ending in `source_text`. Mark any genuinely uncertain spelling instead of guessing.

Lines:
{json.dumps(lines, ensure_ascii=False)}

Return strict JSON:
{{"lines":[{{"id":"","source_text":"","script":"Devanagari|Gurmukhi|Kannada","roman_roundtrip":"","uncertainty":""}}]}}"""
    result = gemini.call(options.model, gemini.key(), prompt, audio=None, timeout=options.timeout)
    rows = result["packet"].get("lines", [])
    by_id, errors = validate_rows(lines, rows, scripts)
    artifact = {"slug": slug, "model_requested": options.model, "result": result, "validation_errors": errors,
                "publication_status": "blocked" if errors else "reviewed"}
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if options.apply and not errors:
        language = languages[0] if languages else ""
        for line_id in {line["id"] for line in lines}:
            data["SONG_LINES"][line_id]["source"] = by_id[line_id]["source_text"]
            data["SONG_LINES"][line_id]["sourceLanguage"] = {"Hindi": "hi", "Sanskrit": "sa", "Punjabi": "pa", "Kannada": "kn"}.get(language, "")
        data["SONG_META"]["sourceStatus"] = "reviewed"
        write_data(path, data)
    return {"slug": slug, "status": artifact["publication_status"], "cost": result.get("usage", {}).get("cost"), "errors": errors}


def main() -> int:
    options = parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        futures = {pool.submit(review, slug, options): slug for slug in options.songs}
        results = []
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"slug": futures[future], "status": "blocked", "error": str(exc)})
    results.sort(key=lambda item: item["slug"])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(result["status"] == "blocked" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
