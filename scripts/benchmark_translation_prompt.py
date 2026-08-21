#!/usr/bin/env python3
"""Run the production gloss/translation prompts against hidden poetic regressions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import bhakti_pipeline as pipeline
import process_song_gemini as gemini


ROOT = Path(__file__).resolve().parents[1]


def load_lines(slug: str) -> dict[str, Any]:
    path = ROOT / "songs" / slug / "data.js"
    script = """const fs=require('fs'),vm=require('vm');const c={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),c,{filename:process.argv[1]});
process.stdout.write(JSON.stringify(c.window.SONG_LINES||{}));"""
    return json.loads(subprocess.run(
        ["node", "-e", script, str(path)], check=True, capture_output=True, text=True
    ).stdout)


def has(pattern: str) -> Callable[[str], bool]:
    compiled = re.compile(pattern, re.I)
    return lambda value: bool(compiled.search(value))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=gemini.MODEL)
    parser.add_argument("--timeout", type=float, default=300)
    options = parser.parse_args()
    cases = [
        ("kakad-aarti", "line-030", "mercy", has(r"look .*mercy"), False),
        ("kakad-aarti", "line-178", "alms_bag", has(r"alms bag"), False),
        ("koi-hor-nahi", "v1a", "breath_agency", has(r"breath.*(?:abandon|leave|release|give up)|(?:give up|release).*breath"), False),
        ("jhoothe-jag-ne", "refrain_b", "inside_image", has(r"bro(?:ke|ken).*?from the (?:very )?inside"), False),
        ("zara-to-itana-bata-do-sai", "refrain_2", "longing_take_hold", has(r"longing.*take hold"), False),
        ("koi-hor-nahi", "refrain", "garment_hem", has(r"hem .*garment"), False),
        ("thanu-karagadavaralli", "ennalli", "palm_context_1", lambda _: True, False),
        ("thanu-karagadavaralli", "karasthala", "palm_dwelling", has(r"(?:palm|cupped hand).*(?:rest|dwell|settle|abode)|(?:rest|dwell|settle|abode).*(?:palm|cupped hand)"), False),
        ("thanu-karagadavaralli", "chennamalli", "palm_context_2", lambda _: True, False),
        ("aisa-pyar-baha-de-maiya", "refrain_d", "sacred_vision", has(r"(?:sacred|blessed) (?:sight|vision)|darshan"), False),
    ]
    cache: dict[str, dict[str, Any]] = {}
    audited_lines = []
    validators: dict[str, tuple[str, Callable[[str], bool], bool]] = {}
    human_baselines: dict[str, str] = {}
    for slug, line_id, label, validator, review_expected in cases:
        if slug not in cache:
            cache[slug] = load_lines(slug)
        line = cache[slug][line_id]
        regression_id = f"{slug}--{line_id}"
        audited_lines.append({"id": regression_id, "source_text": line.get("source", ""),
                              "roman": line["roman"], "kind": "verse"})
        validators[regression_id] = (label, validator, review_expected)
        human_baselines[regression_id] = re.sub(r"\{[^:{}]*:([^{}]*)\}", r"\1", str(line.get("english", "")))
    audited = {"packet": {"verified_lines": audited_lines, "uncertainties": []}}
    api_options = SimpleNamespace(model=options.model, timeout=options.timeout, force=True)
    with tempfile.TemporaryDirectory(prefix="bhakti-translation-regression-") as temporary:
        song_dir = Path(temporary)
        glosses = pipeline.gloss(song_dir, audited, api_options)
        translations = pipeline.translate(song_dir, audited, glosses, {}, api_options)
        baseline_translations = pipeline.translate(
            song_dir, audited, glosses,
            {"providedTranslation": json.dumps(human_baselines, ensure_ascii=False)}, api_options,
        )
    outputs = {row["id"]: row for row in translations["packet"]["translations"]}
    results = []
    for line in audited_lines:
        label, validator, review_expected = validators[line["id"]]
        output = outputs[line["id"]]
        english = str(output["literal_english"])
        review = bool(output.get("human_review_recommended"))
        independent = output.get("independent_review", {})
        independently_flagged = bool(independent.get("human_review_recommended")) or not independent.get("passes", True)
        silently_safe = validator(english)
        passed = (silently_safe or independently_flagged) and (not review_expected or review or independently_flagged)
        results.append({"label": label, "english": english, "passed": passed,
                        "silently_safe": silently_safe,
                        "human_review_recommended": review,
                        "material_alternatives": outputs[line["id"]].get("material_alternatives", []),
                        "fidelity": outputs[line["id"]].get("fidelity", {}),
                        "independent_review": independent})
    summary = {"model": options.model, "passed": sum(result["passed"] for result in results),
               "total": len(results), "results": results,
               "human_baseline": [{"id": line_id,
                                   "expected": human_baselines[line_id],
                                   "actual": next(row["literal_english"] for row in baseline_translations["packet"]["translations"] if row["id"] == line_id),
                                   "preserved": next(row["literal_english"] for row in baseline_translations["packet"]["translations"] if row["id"] == line_id) == human_baselines[line_id]}
                                  for line_id in human_baselines],
               "reported_cost": pipeline.reported_cost(glosses, translations, baseline_translations)}
    summary["human_baselines_preserved"] = sum(item["preserved"] for item in summary["human_baseline"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if (summary["passed"] == summary["total"]
                 and summary["human_baselines_preserved"] == len(human_baselines)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
