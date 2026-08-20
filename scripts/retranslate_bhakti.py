#!/usr/bin/env python3
"""Create gloss-first translation review packets for existing Bhakti readers.

This is intentionally text-only: it does not redownload, retranscribe, or
retime audio. It first rebuilds word glosses, then asks Gemini to derive a
literal English line solely from that gloss record and compare it to the
currently published wording. Public data is not overwritten by this command.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
from pathlib import Path
from typing import Any

import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("songs", nargs="+", help="Song slug(s), or 'all'")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--reuse-glosses", action="store_true",
                        help="Reuse an existing private gloss packet and rerun only the English stage.")
    return parser.parse_args()


def load_lines(slug: str) -> dict[str, Any]:
    data = ROOT / "songs" / slug / "data.js"
    if not data.is_file():
        raise RuntimeError(f"missing data.js for {slug}")
    script = """const fs=require('fs'),vm=require('vm');const ctx={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(ctx.window.SONG_LINES || {}));"""
    output = subprocess.run(["node", "-e", script, str(data)], check=True, text=True, capture_output=True).stdout
    lines = json.loads(output)
    if not lines:
        raise RuntimeError(f"{slug} has no SONG_LINES")
    return lines


def call(prompt: str, options: argparse.Namespace) -> dict[str, Any]:
    return gemini.call(options.model, gemini.key(), prompt, audio=None, timeout=options.timeout)


def run_slug(slug: str, options: argparse.Namespace) -> dict[str, Any]:
    lines = load_lines(slug)
    canonical = [{"id": line_id, "source_text": line.get("source", ""), "roman": line.get("roman", ""),
                  "published_english": line.get("english", ""), "published_words": line.get("words", [])}
                 for line_id, line in lines.items()]
    review_dir = ROOT / "songs" / slug / ".transcription" / "translation-review-gloss-first"
    review_dir.mkdir(parents=True, exist_ok=True)
    existing = review_dir / "review.json"
    prior = json.loads(existing.read_text(encoding="utf-8")) if options.reuse_glosses and existing.is_file() else None
    gloss_prompt = f"""Rebuild literal word glosses for these devotional lyric lines. Work from the supplied source script where present and careful IAST in every case. Segment actual words or meaningful grammatical units, preserve imagery, and state syntax/idiom notes. Do not write fluent sentence translations yet. Mark uncertainty rather than guessing.

Current reader lines (the existing word glosses are comparison evidence, not a baseline to copy):
{json.dumps(canonical, ensure_ascii=False)}

Return strict JSON:
{{"glosses":[{{"id":"line-id","word_glosses":[{{"roman":"","gloss":""}}],"grammar_note":"","uncertainty":""}}]}}"""
    glosses = prior["glosses"] if prior else call(gloss_prompt, options)
    translation_prompt = f"""Write a faithful, complete, idiomatic English reading of each devotional lyric line from the supplied word glosses and grammar notes only. Glosses constrain meaning and grammar; they do not require wooden English or a sequence of gloss synonyms. Preserve the original poetic image, devotional register, and every meaningful emphasis. Do not add interpretation, omit a word, or swap a precise image for a looser synonym. If the published wording is already more precise and natural while remaining faithful to every gloss, retain it. For each line compare the old published English and explain every material wording change. Do not change a line merely for style.

Source/IAST/current English:
{json.dumps(canonical, ensure_ascii=False)}

New gloss record:
{json.dumps(glosses['packet'].get('glosses', []), ensure_ascii=False)}

Return strict JSON:
{{"translations":[{{"id":"line-id","literal_english":"","uncertainty":""}}],"comparison":[{{"id":"line-id","published":"","proposed":"","material_change":false,"reason":""}}]}}"""
    translations = call(translation_prompt, options)
    report = {"slug": slug, "model_requested": options.model, "source_lines": canonical,
              "glosses": glosses, "translations": translations, "reused_glosses": bool(prior),
              "reported_openrouter_cost": sum(float(item.get("usage", {}).get("cost", 0) or 0) for item in (glosses, translations))}
    (review_dir / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"slug": slug, "reported_openrouter_cost": report["reported_openrouter_cost"], "status": "review-required"}


def main() -> int:
    options = parse_args()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
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
