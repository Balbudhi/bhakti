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
    gloss_prompt = f"""Rebuild literal word glosses for these devotional lyric lines. Work from the supplied source script where present and careful IAST in every case. Segment actual words or meaningful grammatical units, preserve imagery, and state syntax/idiom notes. Do not write fluent sentence translations yet. Mark uncertainty rather than guessing.

Current reader lines (the existing word glosses are comparison evidence, not a baseline to copy):
{json.dumps(canonical, ensure_ascii=False)}

Return strict JSON:
{{"glosses":[{{"id":"line-id","word_glosses":[{{"roman":"","gloss":""}}],"grammar_note":"","uncertainty":""}}]}}"""
    glosses = call(gloss_prompt, options)
    translation_prompt = f"""Write a literal English reading of each devotional lyric line from the supplied new word glosses and grammar notes only. Preserve the poetic image but do not add interpretation or swap a word for a looser synonym. For each line compare the old published English and explain every material wording change. Do not change a line merely for style.

Source/IAST/current English:
{json.dumps(canonical, ensure_ascii=False)}

New gloss record:
{json.dumps(glosses['packet'].get('glosses', []), ensure_ascii=False)}

Return strict JSON:
{{"translations":[{{"id":"line-id","literal_english":"","uncertainty":""}}],"comparison":[{{"id":"line-id","published":"","proposed":"","material_change":false,"reason":""}}]}}"""
    translations = call(translation_prompt, options)
    report = {"slug": slug, "model_requested": options.model, "source_lines": canonical,
              "glosses": glosses, "translations": translations,
              "reported_openrouter_cost": sum(float(item.get("usage", {}).get("cost", 0) or 0) for item in (glosses, translations))}
    (review_dir / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"slug": slug, "reported_openrouter_cost": report["reported_openrouter_cost"], "status": "review-required"}


def main() -> int:
    options = parse_args()
    slugs = sorted(path.name for path in (ROOT / "songs").iterdir() if path.is_dir()) if options.songs == ["all"] else options.songs
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        results = list(pool.map(lambda slug: run_slug(slug, options), slugs))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
