#!/usr/bin/env python3
"""Move exact repeated multi-word lyric text into SONG_SEQUENCE.repeats.

The public reader renders a compact ×N marker for immediate identical
performances.  Older intake records sometimes instead embedded N copies in one
line object, creating a wall of duplicate source, IAST, and English.  A single
word repeated as part of a chant (for example ``Rāma Rāma``) is deliberately
left intact: this tool handles only exact repeated phrases of two or more
words.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import repair_deity_glosses as reader_data


ROOT = Path(__file__).resolve().parents[1]
SLOT = re.compile(r"\{([0-9,]+):([^}]*)\}")


def key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def repeat_factor(words: list[dict[str, Any]]) -> int:
    tokens = [key(word.get("roman")) for word in words]
    if len(tokens) < 4 or any(not token for token in tokens):
        return 1
    for period in range(2, len(tokens) // 2 + 1):
        if len(tokens) % period == 0 and all(token == tokens[index % period] for index, token in enumerate(tokens)):
            return len(tokens) // period
    return 1


def first_iteration_english(english: str, period: int) -> str | None:
    matches = list(SLOT.finditer(english))
    selected = [match for match in matches if all(int(index) < period for index in match.group(1).split(","))]
    if not selected:
        return None
    # English slots preserve the displayed order.  Retain every character up
    # to the final slot belonging to the first performance, including natural
    # function words between slots.
    last = selected[-1]
    return english[:last.end()].strip()


def first_iteration_source(line: dict[str, Any], period: int) -> tuple[str, list[dict[str, Any]]] | None:
    mapped = line.get("sourceWords")
    if not isinstance(mapped, list):
        return None
    first: list[dict[str, Any]] = []
    for item in mapped:
        if not isinstance(item, dict):
            return None
        indices = item.get("wordIndices")
        if not isinstance(indices, list) or not indices:
            return None
        if all(isinstance(index, int) and index < period for index in indices):
            first.append({"text": item.get("text", ""), "wordIndices": list(indices)})
    if not first:
        return None
    return " ".join(str(item["text"]).strip() for item in first).strip(), first


def normalize_page(page: dict[str, Any]) -> int:
    lines = page.get("SONG_LINES", {})
    sequence = page.get("SONG_SEQUENCE", [])
    changed = 0
    for ref, line in lines.items():
        if not isinstance(line, dict) or not isinstance(line.get("words"), list):
            continue
        factor = repeat_factor(line["words"])
        if factor == 1:
            continue
        period = len(line["words"]) // factor
        source = first_iteration_source(line, period)
        english = first_iteration_english(str(line.get("english") or ""), period)
        if source is None or english is None:
            continue
        line["words"] = line["words"][:period]
        line["roman"] = " ".join(str(word.get("roman") or "").strip() for word in line["words"]).strip()
        line["source"], line["sourceWords"] = source
        line["english"] = english
        for entry in sequence:
            if entry.get("ref") == ref:
                entry["repeats"] = int(entry.get("repeats") or 1) * factor
        changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report affected lines without changing files")
    options = parser.parse_args()
    affected: dict[str, int] = {}
    for path in sorted((ROOT / "songs").glob("*/data.js")):
        page = reader_data.load(path)
        count = normalize_page(page)
        if count:
            affected[path.parent.name] = count
            if not options.check:
                reader_data.write(path, page)
    print(json.dumps({"songs": affected, "count": sum(affected.values())}, ensure_ascii=False, indent=2))
    return 1 if options.check and affected else 0


if __name__ == "__main__":
    raise SystemExit(main())
