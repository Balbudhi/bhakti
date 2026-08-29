#!/usr/bin/env python3
"""Adapt the reviewed Viṣṇu Sahasranāma reader into a Bhakti song packet.

This is a deterministic importer: it copies the reviewed Sanskrit, existing
start timings, and the Vedānta site's finalized site-generated Simplified
summaries. The summaries are derived from Chinmayananda's commentary but are
not his translation and receive no translator credit. It never calls a model.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import bhakti_pipeline as pipeline
import source_word_map


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = Path("/Users/eeshan/Dev/vedanta-timeline")
SLUG = "vishnu-sahasranama"


def literal_and_segments(template: str) -> tuple[str, list[dict[str, Any]]]:
    parts: list[dict[str, Any]] = []
    cursor = 0
    for match in re.finditer(r"\{([\d,\s]+):([^}]*)\}", template):
        if match.start() > cursor:
            parts.append({"text": template[cursor:match.start()], "word_indices": []})
        parts.append({"text": match.group(2), "word_indices": [int(value) for value in match.group(1).split(",")]})
        cursor = match.end()
    if cursor < len(template):
        parts.append({"text": template[cursor:], "word_indices": []})
    return "".join(part["text"] for part in parts), parts


def simple_word(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "roman": str(raw.get("surface_iast") or raw.get("iast") or "").strip(),
        "citationRoman": str(raw.get("citation_iast") or raw.get("iast") or raw.get("surface_iast") or "").strip(),
        "deva": str(raw.get("deva") or "").strip(),
        "gloss": str(raw.get("gloss") or raw.get("whole_gloss") or "").strip(),
        "analysis": str(raw.get("analysis") or "").strip(),
        "concept_key": "",
        "preserve_in_english": False,
    }


def frame() -> dict[str, str]:
    return {field: "" for field in pipeline.SEMANTIC_FRAME_FIELDS}


def concise_name_analysis(analysis: dict[str, Any]) -> str:
    pieces = []
    for part in analysis.get("parts", []):
        if part.get("kind") == "ending":
            continue
        form = str(part.get("form_iast") or "").strip()
        gloss = str(part.get("gloss") or "").strip().rstrip(".")
        if form and gloss:
            pieces.append(f"{form} — {gloss}")
    root = analysis.get("root") or {}
    root_form = str(root.get("form") or "").strip()
    root_gloss = str(root.get("gloss") or "").strip().removeprefix("to ").rstrip(".")
    if root_form and root_gloss and not any(piece.startswith(root_form) for piece in pieces):
        pieces.append(f"{root_form} — {root_gloss}")
    morph = str(analysis.get("morph") or "").strip().rstrip(".")
    if morph:
        pieces.append(morph)
    result = " · ".join(dict.fromkeys(pieces))
    if not result:
        raise RuntimeError(f"name {analysis.get('number')} lacks concise analysis content")
    return result


def preface_units(reader: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    return [(unit, "invocation") for group in reader["preface"]["groups"] for unit in group["units"]]


def name_stanza(stanza: dict[str, Any]) -> tuple[dict[str, Any], str]:
    words = []
    for name in stanza["names"]:
        analysis = name.get("word_analysis") or {}
        words.append({
            "surface_iast": name.get("surface_iast") or name.get("citation_iast"),
            "iast": name.get("citation_iast"),
            "citation_iast": name.get("citation_iast"),
            "deva": analysis.get("citation_devanagari") or name.get("deva"),
            "gloss": name.get("meaning") or analysis.get("whole_gloss"),
            "analysis": concise_name_analysis(analysis),
        })
    return {
        "id": f"stanza-{stanza['number']}",
        "devanagari": stanza["devanagari"],
        "iast": " ".join(str(word["surface_iast"]) for word in words),
        "words": words,
        "english": " · ".join(str(word["gloss"]) for word in words),
        "name_sequence": True,
    }, "verse"


def imported_units(reader: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    units = preface_units(reader)
    units.extend(name_stanza(stanza) for stanza in reader["stanzas"])
    units.extend((unit, "closing") for unit in reader["postlude"])
    return units


def reader_job(reader: dict[str, Any]) -> dict[str, Any]:
    section_notices = []
    cursor = 0
    for group in reader["preface"]["groups"]:
        section_notices.append({"sequenceIndex": cursor, "title": str(group["title"])})
        cursor += len(group["units"])
    section_notices.append({"sequenceIndex": cursor, "title": "The thousand names"})
    labels = {}
    for stanza in reader["stanzas"]:
        numbers = [int(number) for number in stanza["name_numbers"]]
        labels[f"stanza-{stanza['number']}"] = (
            f"Names {numbers[0]}–{numbers[-1]}" if len(numbers) > 1 else f"Name {numbers[0]}"
        )
    section_notices.append({"sequenceIndex": cursor + len(reader["stanzas"]), "title": "Closing"})
    return {
        "slug": SLUG, "title": "Viṣṇu Sahasranāma", "writer": "Vyāsa",
        "translator": "", "translatorAttribution": "",
        "singer": str(reader["audio"]["performer"]), "languages": ["Sanskrit"],
        "subjectTags": ["Viṣṇu"],
        "songAssetVersion": "contract-20260828-11",
        "dataAssetVersion": "contract-20260828-9",
        "searchAliases": ["Vishnu Sahasranama", "Vishnu Sahastranam", "Vishnu Sahasranam",
                          "Sanjeev Abhyankar Vishnu Sahasranama"],
        "sectionNotices": section_notices, "lineLabels": labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--generate", action="store_true", help="Regenerate the public song and catalogue")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    reader_path = source_root / "gita" / "vishnu-sahasranama" / "reader.json"
    reader = json.loads(reader_path.read_text(encoding="utf-8"))
    audio_by_id = {unit["id"]: unit for unit in reader["audio"]["units"]}
    song_dir = ROOT / "songs" / SLUG
    packet_dir = song_dir / ".transcription" / "pipeline"
    packet_dir.mkdir(parents=True, exist_ok=True)

    lines: list[dict[str, Any]] = []
    glosses: list[dict[str, Any]] = []
    translations: list[dict[str, Any]] = []
    timing: list[dict[str, Any]] = []
    for unit, kind in imported_units(reader):
        unit_id = str(unit["id"])
        audio = audio_by_id.get(unit_id)
        if not audio:
            raise RuntimeError(f"missing reviewed timing for {unit_id}")
        words = [simple_word(word, index) for index, word in enumerate(unit["words"])]
        if not all(word["roman"] and word["gloss"] for word in words):
            raise RuntimeError(f"missing simple word meaning for {unit_id}")
        source = str(unit["devanagari"])
        roman = str(unit["iast"])
        if unit.get("name_sequence"):
            segments = []
            for index, word in enumerate(words):
                if index:
                    segments.append({"text": " · ", "word_indices": []})
                segments.append({"text": word["gloss"], "word_indices": [index]})
            english = "".join(part["text"] for part in segments)
        else:
            english, segments = literal_and_segments(str(unit["english"]))
        lines.append({"id": unit_id, "source_text": source, "roman": roman, "kind": kind,
                      "name_table": bool(unit.get("name_sequence")), "translation_notes": ""})
        glosses.append({"id": unit_id, "word_glosses": words, "semantic_frame": frame(), "grammar_note": "", "uncertainty": ""})
        translations.append({
            "id": unit_id, "literal_english": english, "segments": segments,
            "material_alternatives": [], "human_review_recommended": False,
            "choice_note": "Site-generated Simplified summary imported from the reviewed Vedānta reader; derived from Chinmayananda's explanation but not credited as his wording or translation.",
            "fidelity": {"agency_and_image_preserved": True, "all_meaning_accounted_for": True,
                         "unsupported_additions": [], "notes": "Imported from the independently validated Simplified layer."},
            "uncertainty": "",
        })
        timing.append({"ref": unit_id, "section": kind, "repeats": 1,
                       "start": float(audio["start"]), "end": float(audio["end"])})

    name_words = [
        word
        for line in lines
        if line.get("name_table")
        for word in next(row["word_glosses"] for row in glosses if row["id"] == line["id"])
    ]
    if len(name_words) != 1000:
        raise RuntimeError(f"expected exactly 1,000 imported names, found {len(name_words)}")
    if any(not word.get("analysis") or word["analysis"] == word.get("gloss") for word in name_words):
        raise RuntimeError("every imported name requires a non-redundant concise analysis hover")

    audited = {"packet": {"metadata": {"languages": ["Sanskrit"]}, "verified_lines": lines,
                            "performance_order": [{"line_id": line["id"], "occurrence": 1} for line in lines],
                            "changes": [], "uncertainties": []},
               "imported_from": str(reader_path), "source_first_witness": True}
    timing_packet = {"duration_seconds": float(reader["audio"]["duration_seconds"]),
                     "ordered_occurrences": [{"ref": item["ref"]} for item in timing], "sequence": timing,
                     "validation_errors": [], "uncertain_occurrence_ids": [], "publication_status": "review-required"}
    gloss_packet = {"packet": {"glosses": glosses}, "gloss_contract_version": pipeline.GLOSS_CONTRACT_VERSION,
                    "imported_from": str(reader_path)}
    translation_packet = {"packet": {"translations": translations, "comparison": []},
                          "input_contract_version": pipeline.TRANSLATION_INPUT_VERSION,
                          "imported_from": str(reader_path)}
    errors = pipeline.publication_errors(audited, timing_packet, gloss_packet, translation_packet)
    if errors:
        raise RuntimeError("import violates Bhakti contract: " + "; ".join(errors[:8]))
    source = {"source_url": reader["audio"]["src"], "title": reader["title"],
              "artist": reader["audio"]["performer"], "duration_seconds": reader["audio"]["duration_seconds"],
              "review_note": "Imported from the reviewed Vedānta reader; Sanskrit and site-generated Simplified summaries passed its full-population checks. No translator is credited."}
    pipeline.write_json(song_dir / ".transcription" / "source.json", source)
    pipeline.write_json(packet_dir / "02-transcript-audit.json", audited)
    pipeline.write_json(packet_dir / "03-timing.json", timing_packet)
    pipeline.write_json(packet_dir / "04-glosses.json", gloss_packet)
    pipeline.write_json(packet_dir / "05-translation.json", translation_packet)
    if args.generate:
        pipeline.generate(
            song_dir,
            reader_job(reader),
            source,
            audited,
            timing_packet,
            gloss_packet,
            translation_packet,
            write_catalogue_after=False,
        )
    print(json.dumps({"slug": SLUG, "lines": len(lines), "duration": reader["audio"]["duration_seconds"],
                      "generated": args.generate}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
